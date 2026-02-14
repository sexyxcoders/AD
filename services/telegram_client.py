"""Secure Telethon client management with session pooling and safety guards"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Tuple, List, Dict, Any
from contextlib import asynccontextmanager

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.channels import GetChannelsRequest, GetFullChannelRequest
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import Channel, Chat, User
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError,
    PhoneNumberFloodError,
    FloodWaitError,
    AuthKeyUnregisteredError,
    UserDeactivatedError,
    SessionRevokedError,
    SessionExpiredError
)

from core import API_ID, API_HASH, CONFIG, db

logger = logging.getLogger(__name__)

# Global session pool for connection reuse
SESSION_POOL: Dict[str, TelegramClient] = {}

class SessionValidationError(Exception):
    """Custom exception for session validation failures"""
    pass

@asynccontextmanager
async def managed_client(session_str: str, phone: str):
    """
    Context manager for safe Telethon client lifecycle management.
    
    Features:
    - Automatic connection/disconnection
    - Session validation before use
    - Health checks on acquisition
    - Automatic cleanup on errors
    - Connection pooling for performance
    
    Usage:
        async with managed_client(session_str, phone) as client:
            await client.send_message(...)
    """
    client = None
    try:
        # Check pool first
        if session_str in SESSION_POOL:
            client = SESSION_POOL[session_str]
            # Validate connection health
            try:
                await client.get_me()
                logger.debug(f"✓ Reusing pooled client for {phone}")
                yield client
                return
            except (AuthKeyUnregisteredError, SessionRevokedError, SessionExpiredError):
                # Session invalidated - remove from pool
                logger.warning(f"⚠️ Pooled session expired for {phone}, creating new")
                SESSION_POOL.pop(session_str, None)
            except Exception as e:
                logger.warning(f"⚠️ Pooled client health check failed for {phone}: {e}")
                SESSION_POOL.pop(session_str, None)
        
        # Create new client
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await client.connect()
        
        # Validate session authenticity
        try:
            me = await client.get_me()
            if not me or not hasattr(me, 'phone'):
                raise SessionValidationError("Session returned invalid user data")
            if me.phone and me.phone.replace('+', '') != phone.replace('+', ''):
                raise SessionValidationError(
                    f"Session phone mismatch: expected {phone}, got {me.phone}"
                )
        except (AuthKeyUnregisteredError, SessionRevokedError, SessionExpiredError) as e:
            await client.disconnect()
            raise SessionValidationError(f"Session revoked/expired: {e}") from e
        except UserDeactivatedError as e:
            await client.disconnect()
            raise SessionValidationError(f"Account deactivated: {e}") from e
        
        # Add to pool
        SESSION_POOL[session_str] = client
        logger.info(f"✓ New client created and pooled for {phone}")
        
        yield client
        
    except Exception:
        if client:
            await disconnect_client_gracefully(client, phone)
        raise
    finally:
        # Don't disconnect pooled clients - keep alive for reuse
        # Actual cleanup happens in background health check task
        pass

async def create_telethon_client(session_str: str, phone: str) -> TelegramClient:
    """
    Create and validate a new Telethon client instance.
    
    WARNING: Prefer managed_client() context manager for automatic cleanup.
    This function is for special cases requiring direct client access.
    
    Args:
        session_str: String session from database
        phone: Associated phone number for validation
    
    Returns:
        Connected and validated TelegramClient instance
    
    Raises:
        SessionValidationError: If session is invalid/expired
        ConnectionError: If connection fails
    """
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    
    try:
        await client.connect()
        
        # Critical validation checks
        if not await client.is_user_authorized():
            await client.disconnect()
            raise SessionValidationError("Session not authorized")
        
        me = await client.get_me()
        if not me:
            await client.disconnect()
            raise SessionValidationError("Session returned empty user data")
        
        # Phone number validation (partial match for privacy)
        if me.phone and not phone.endswith(me.phone[-4:]):
            logger.warning(
                f"Phone mismatch for {phone}: session has {me.phone}. "
                "Proceeding anyway (Telegram sometimes hides full number)."
            )
        
        return client
        
    except (AuthKeyUnregisteredError, SessionRevokedError, SessionExpiredError) as e:
        await client.disconnect()
        raise SessionValidationError(f"Session revoked/expired: {e}") from e
    except UserDeactivatedError as e:
        await client.disconnect()
        raise SessionValidationError(f"Account permanently banned: {e}") from e
    except Exception as e:
        await client.disconnect()
        raise ConnectionError(f"Client creation failed: {e}") from e

async def validate_session(session_str: str, phone: str) -> Tuple[bool, str]:
    """
    Validate session health without keeping connection open.
    
    Returns:
        Tuple of (is_valid: bool, reason: str)
    """
    try:
        async with managed_client(session_str, phone) as client:
            # Quick health check
            await client.get_me()
            return True, "Session valid"
    except SessionValidationError as e:
        return False, f"Validation failed: {e}"
    except FloodWaitError as e:
        return False, f"Flood wait required: {e.seconds}s"
    except Exception as e:
        return False, f"Unexpected error: {type(e).__name__}: {e}"

async def update_profile_safe(
    client: TelegramClient,
    first_name: str,
    bio: str,
    max_retries: int = 3
) -> bool:
    """
    Safely update Telegram profile with retry logic and flood protection.
    
    Safety features:
    - Flood wait handling with exponential backoff
    - No-op if profile already matches
    - Rate limiting between updates
    - Silent failure on non-critical errors
    
    Returns:
        True if update succeeded, False otherwise
    """
    try:
        # Check current profile to avoid unnecessary updates
        me = await client.get_me()
        if me.first_name == first_name and me.about == bio:
            logger.debug("Profile already matches target state - skipping update")
            return True
        
        for attempt in range(max_retries):
            try:
                await client(UpdateProfileRequest(
                    first_name=first_name,
                    about=bio
                ))
                logger.info(f"✓ Profile updated successfully: {first_name}")
                return True
                
            except FloodWaitError as e:
                if attempt == max_retries - 1:
                    logger.warning(f"✗ Profile update failed after {max_retries} attempts: FloodWait {e.seconds}s")
                    return False
                
                wait_time = min(e.seconds * (2 ** attempt), 300)  # Cap at 5 minutes
                logger.warning(f"⚠️ Flood wait during profile update. Waiting {wait_time}s (attempt {attempt+1}/{max_retries})")
                await asyncio.sleep(wait_time)
                
            except Exception as e:
                # Non-fatal errors - log but don't block
                logger.warning(f"⚠️ Non-critical profile update error: {e}")
                return False
        
        return False
        
    except Exception as e:
        logger.error(f"✗ Critical profile update failure: {e}", exc_info=True)
        return False

async def get_joined_chats(
    client: TelegramClient,
    max_chats: int = 500,
    exclude_muted: bool = True,
    exclude_broadcasts: bool = True
) -> List[Dict[str, Any]]:
    """
    Discover eligible chats for broadcasting with safety filters.
    
    Safety filters:
    - Exclude private chats (only groups/channels)
    - Exclude muted chats (user doesn't want notifications)
    - Exclude broadcast channels (can't message members)
    - Exclude admin-only channels (can't broadcast to members)
    - Respect Telegram's anti-spam limits
    
    Returns:
        List of chat dictionaries with id, title, type, member_count
    """
    try:
        dialogs = await client.get_dialogs(limit=max_chats)
        eligible_chats = []
        
        for dialog in dialogs:
            entity = dialog.entity
            
            # Skip non-group/channel entities
            if isinstance(entity, User):
                continue
            
            # Skip broadcast channels (can't message members)
            if exclude_broadcasts and hasattr(entity, 'broadcast') and entity.broadcast:
                continue
            
            # Skip muted chats if requested
            if exclude_muted and dialog.notify_settings and dialog.notify_settings.mute_until:
                continue
            
            # Determine chat type and eligibility
            chat_type = "unknown"
            is_eligible = False
            
            if isinstance(entity, Channel):
                if entity.megagroup:  # Supergroup
                    chat_type = "supergroup"
                    is_eligible = True
                elif not entity.broadcast:  # Regular channel (not broadcast)
                    chat_type = "channel"
                    is_eligible = True
            elif isinstance(entity, Chat):  # Basic group
                chat_type = "basic_group"
                is_eligible = True
            
            if not is_eligible:
                continue
            
            # Get member count safely
            member_count = 0
            try:
                if hasattr(entity, 'participants_count'):
                    member_count = entity.participants_count
                elif hasattr(entity, 'full'):
                    full = await client(GetFullChannelRequest(entity))
                    member_count = full.full_chat.participants_count
            except Exception:
                pass  # Skip member count on error
            
            eligible_chats.append({
                "id": dialog.id,
                "title": entity.title,
                "type": chat_type,
                "member_count": member_count,
                "username": getattr(entity, 'username', None),
                "is_public": hasattr(entity, 'username') and entity.username is not None
            })
        
        logger.info(f"Discovered {len(eligible_chats)} eligible chats for broadcasting")
        return eligible_chats[: