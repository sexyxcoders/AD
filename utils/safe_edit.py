"""Safe Telegram message editing utilities with comprehensive error handling"""
import asyncio
import logging
from typing import Optional, Union, TYPE_CHECKING
from telegram import Update, Message, CallbackQuery, InlineKeyboardMarkup, InputMediaPhoto

if TYPE_CHECKING:
    from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

class MessageEditError(Exception):
    """Custom exception for message editing failures"""
    pass

async def safe_edit_or_send(
    query_or_message: Union[CallbackQuery, Message],
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    photo_url: Optional[str] = None,
    parse_mode: str = "MarkdownV2",
    max_retries: int = 2
) -> Optional[Message]:
    """
    Safely edit a message or send a new one with automatic fallbacks.
    
    Features:
    - Automatic fallback from edit → new message on failure
    - Media type handling (text vs photo)
    - Retry logic for transient errors
    - Comprehensive error suppression for user-facing operations
    - Automatic old message cleanup to prevent clutter
    
    Args:
        query_or_message: CallbackQuery or Message object to edit/send to
        text: Message text content (properly escaped for MarkdownV2)
        reply_markup: Optional inline keyboard markup
        photo_url: Optional photo URL for media messages
        parse_mode: Telegram parse mode ("MarkdownV2", "HTML", or None)
        max_retries: Number of retry attempts for transient errors
    
    Returns:
        The resulting Message object or None if all attempts fail
    
    Raises:
        MessageEditError: Only on complete failure after retries (rare)
    """
    for attempt in range(max_retries + 1):
        try:
            # Determine context (callback query vs direct message)
            is_callback = isinstance(query_or_message, CallbackQuery)
            chat_id = query_or_message.message.chat_id if is_callback else query_or_message.chat_id
            message_id = query_or_message.message.message_id if is_callback else query_or_message.message_id
            
            # Attempt to edit existing message
            if is_callback:
                await query_or_message.answer()  # Always answer callbacks first
            
            if photo_url:
                # Handle photo messages
                try:
                    if is_callback and query_or_message.message.photo:
                        # Edit existing photo
                        return await query_or_message.edit_message_media(
                            media=InputMediaPhoto(media=photo_url, caption=text),
                            reply_markup=reply_markup
                        )
                    else:
                        # Send new photo
                        msg = await query_or_message.message.reply_photo(
                            photo=photo_url,
                            caption=text,
                            reply_markup=reply_markup,
                            parse_mode=parse_mode
                        )
                        # Clean up old message if editing failed
                        if is_callback:
                            await safe_delete_message(query_or_message.message)
                        return msg
                except Exception as e:
                    logger.debug(f"Photo edit failed (attempt {attempt+1}): {e}")
                    # Fall through to text message fallback
                    photo_url = None  # Disable photo for retry
            
            # Handle text messages
            try:
                if is_callback:
                    return await query_or_message.edit_message_text(
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode
                    )
                else:
                    return await query_or_message.edit_text(
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode
                    )
            except Exception as e:
                logger.debug(f"Text edit failed (attempt {attempt+1}): {e}")
                # Fall through to send new message
                
            # Fallback: send new message
            if is_callback:
                msg = await query_or_message.message.reply_text(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
            else:
                msg = await query_or_message.reply_text(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
            
            # Clean up old message to prevent clutter
            if is_callback:
                await safe_delete_message(query_or_message.message)
            
            return msg
            
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)[:100]
            
            # Non-retryable errors - fail immediately
            if error_type in [
                'BadRequest', 
                'Forbidden', 
                'ChatNotFound', 
                'UserIsBlocked',
                'BotBlocked'
            ]:
                logger.warning(f"Non-retryable error during message edit: {error_type}: {error_msg}")
                raise MessageEditError(f"Message delivery failed: {error_msg}") from e
            
            # Retryable errors - wait and retry
            if attempt < max_retries:
                wait_time = 2 ** attempt  # Exponential backoff
                logger.debug(f"Retryable error (attempt {attempt+1}/{max_retries+1}), waiting {wait_time}s: {error_type}")
                await asyncio.sleep(wait_time)
                continue
            
            # Final failure after retries
            logger.error(f"Message edit failed after {max_retries+1} attempts: {error_type}: {error_msg}")
            raise MessageEditError(f"Message delivery failed after retries: {error_msg}") from e
    
    return None  # Should never reach here due to exception raising

async def safe_delete_message(message: Message, silent: bool = True) -> bool:
    """
    Safely delete a message with error suppression.
    
    Args:
        message: Telegram Message object to delete
        silent: If True, suppress errors (default); False raises exceptions
    
    Returns:
        True if deletion succeeded, False otherwise
    """
    try:
        await message.delete()
        return True
    except Exception as e:
        if not silent:
            raise
        error_type = type(e).__name__
        if error_type not in ['MessageToDeleteNotFound', 'MessageCantBeDeleted', 'BadRequest']:
            logger.debug(f"Non-critical message deletion error: {error_type}: {e}")
        return False

async def safe_answer_callback(
    query: CallbackQuery,
    text: Optional[str] = None,
    show_alert: bool = False,
    url: Optional[str] = None,
    cache_time: int = 0,
    silent: bool = True
) -> bool:
    """
    Safely answer a callback query with error suppression.
    
    Prevents "query is too old" errors from crashing the bot.
    
    Args:
        query: CallbackQuery to answer
        text: Optional notification text
        show_alert: Show as alert dialog instead of toast
        url: Optional URL to open (for game callbacks)
        cache_time: Cache time for callback answer
        silent: Suppress errors if True (default)
    
    Returns:
        True if answered successfully, False otherwise
    """
    try:
        await query.answer(
            text=text,
            show_alert=show_alert,
            url=url,
            cache_time=cache_time
        )
        return True
    except Exception as e:
        if not silent:
            raise
        error_type = type(e).__name__
        # Expected errors for old callbacks
        if "Query is too old" in str(e) or error_type in [
            'InvalidQueryID',
            'QueryIdInvalid'
        ]:
            logger.debug(f"Suppressing expected callback error: {e}")
            return False
        logger.warning(f"Unexpected callback answer error: {error_type}: {e}")
        return False

def escape_markdown_v2(text: str) -> str:
    """
    Escape text for Telegram MarkdownV2 parse mode.
    
    Handles all special characters defined in Telegram Bot API:
    _ * [ ] ( ) ~ ` > # + - = | { } . !
    
    Args:
        text: Raw text to escape
    
    Returns:
        Escaped text safe for MarkdownV2
    
    Example:
        >>> escape_markdown_v2("Hello *world*!")
        'Hello \\*world\\*\\!'
    """
    # Order matters: escape backslashes first, then other special chars
    escape_chars = r'_[]()~`>#+-=|{}.!'
    for char in escape_chars:
        text = text.replace(char, '\\' + char)
    return text

def format_error_message(error: Exception, max_length: int = 200) -> str:
    """
    Format exception into user-friendly error message.
    
    Args:
        error: Exception instance
        max_length: Maximum length of returned message
    
    Returns:
        Formatted error message suitable for user display
    """
    error_type = type(error).__name__
    error_msg = str(error).strip()
    
    # Map technical errors to user-friendly messages
    friendly_messages = {
        'FloodWaitError': 'Telegram rate limit reached. Please wait a moment and try again.',
        'SessionPasswordNeededError': 'Two-factor authentication required. Please enter your password.',
        'PhoneCodeInvalidError': 'Invalid verification code. Please check and try again.',
        'PhoneNumberBannedError': 'This phone number is banned by Telegram.',
        'UserDeactivatedError': 'This account has been deactivated by Telegram.',
        'AuthKeyUnregisteredError': 'Session expired. Please re-authenticate your account.',
        'ConnectionError': 'Network connection failed. Please check your internet connection.',
    }
    
    friendly = friendly_messages.get(error_type)
    if friendly:
        return f"⚠️ {friendly}"
    
    # Generic fallback with length limiting
    if len(error_msg) > max_length:
        error_msg = error_msg[:max_length-3] + "..."
    
    return f"⚠️ Operation failed: {error_msg}" if error_msg else "⚠️ An unexpected error occurred"