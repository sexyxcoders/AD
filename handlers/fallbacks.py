import logging
import traceback
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from keyboards.common_kb import get_dashboard_keyboard

logger = logging.getLogger(__name__)

async def noop_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle noop callbacks (buttons that should do nothing)"""
    await update.callback_query.answer()

async def unknown_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages that don't match any active state"""
    # Only respond in private chats
    if not update.message or not update.message.chat.type == "private":
        return
    
    # Don't respond to commands
    if update.message.text and update.message.text.startswith("/"):
        return
    
    await update.message.reply_text(
        "🤔 I'm not sure what you mean.\n\n"
        "Use the dashboard buttons to navigate, or type /start to restart.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 Go to Dashboard", callback_data="nav|dashboard")
        ]])
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Global error handler for uncaught exceptions"""
    logger.error(f"Exception while handling update {update}", exc_info=context.error)
    
    # Extract traceback for debugging
    tb = "".join(traceback.format_exception(
        type(context.error),
        context.error,
        context.error.__traceback__
    ))
    logger.debug(f"Full traceback:\n{tb}")
    
    # User-friendly message
    error_msg = (
        "❌ An unexpected error occurred!\n\n"
        "Our team has been notified. Please try again later or restart with /start."
    )
    
    # Try to notify user if possible
    try:
        if update and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=error_msg,
                reply_markup=get_dashboard_keyboard()
            )
    except Exception as send_error:
        logger.error(f"Failed to send error message to user: {send_error}")
    
    # Cleanup any stuck user states
    if update and update.effective_user:
        user_id = update.effective_user.id
        if 'user_states' in context.bot_data and user_id in context.bot_data['user_states']:
            state = context.bot_data['user_states'][user_id]
            if hasattr(state, 'client') and state.client:
                try:
                    await state.client.disconnect()
                except:
                    pass
            state.reset()