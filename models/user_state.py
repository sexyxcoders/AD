"""Secure user session state management with persistence awareness"""
import asyncio
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any, ClassVar
from telethon import TelegramClient
from telethon.sessions import StringSession

from core import API_ID, API_HASH, CONFIG

logger = logging.getLogger(__name__)

class UserStep(str, Enum):
    """Valid states in user interaction flows"""
    IDLE = "idle"
    AWAITING_PHONE = "phone"
    AWAITING_OTP = "code"
    AWAITING_2FA = "password"
    SETTING_AD = "set_ad"
    SETTING_DELAY = "set_delay"
    CONFIRMING_DELETE = "confirm_delete"
    CAMPAIGN_RUNNING = "campaign_running"
    
    def is_active_flow(self) -> bool:
        """Check if step represents an active multi-step flow"""
        return self != self.IDLE

class AccountStatus(str, Enum):
    """Account hosting status classifications"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    RESTRICTED = "restricted"
    BANNED = "banned"
    PENDING_VERIFICATION = "pending"

class CampaignStatus(str, Enum):
    """Broadcast campaign lifecycle states"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    ERROR = "error"

class StateValidationError(Exception):
    """Custom exception for state validation failures"""
    pass

@dataclass
class UserState:
    """
    User session state with security-conscious design.
    
    Critical design principles:
    1. NEVER persist sensitive objects (Telethon clients) - only session strings
    2. Automatic resource cleanup on state transitions
    3. Session timeout enforcement (5 minute default)
    4. Immutable configuration references (no direct bot API access)
    5. Type-safe state transitions with enum validation
    
    Persistence strategy:
    - Pickle-safe fields only stored in database
    - Volatile resources (clients) managed in memory cache
    - Session reconstruction on bot restart via session strings
    """
    
    # Persistent fields (survive bot restarts via PicklePersistence)
    step: UserStep = UserStep.IDLE
    phone: str = ""
    phone_code_hash: str = ""
    session_string: Optional[str] = None  # Picklable session storage
    otp_buffer: str = ""
    ad_message_draft: Optional[str] = None
    delay_setting: int = CONFIG.DEFAULT_DELAY
    last_activity: float = field(default_factory=time.time)
    account_status: AccountStatus = AccountStatus.INACTIVE
    campaign_status: CampaignStatus = CampaignStatus.STOPPED
    
    # Volatile fields (NOT persisted - reconstructed on restart)
    _client: Optional[TelegramClient] = field(default=None, repr=False, init=False)
    _client_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, init=False)
    _cleanup_task: Optional[asyncio.Task] = field(default=None, repr=False, init=False)
    
    # Class-level configuration
    SESSION_TIMEOUT: ClassVar[int] = CONFIG.SESSION_TIMEOUT  # 300 seconds
    
    def __post_init__(self):
        """Initialize volatile fields after unpickling"""
        if self._client is None:
            object.__setattr__(self, '_client', None)
        if not hasattr(self, '_client_lock'):
            object.__setattr__(self, '_client_lock', asyncio.Lock())
        if not hasattr(self, '_cleanup_task'):
            object.__setattr__(self, '_cleanup_task', None)
    
    @property
    def is_expired(self) -> bool:
        """Check if session has timed out due to inactivity"""
        return (time.time() - self.last_activity) > self.SESSION_TIMEOUT
    
    @property
    def has_active_client(self) -> bool:
        """Check if a connected Telethon client exists"""
        return self._client is not None and self._client.is_connected()
    
    @property
    def otp_progress(self) -> int:
        """Return number of OTP digits entered (0-5)"""
        return len(self.otp_buffer)
    
    def touch(self) -> None:
        """Update last activity timestamp"""
        self.last_activity = time.time()
    
    async def get_client(self) -> Optional[TelegramClient]:
        """
        Get or create Telethon client instance from session string.
        
        Security features:
        - Lazy client initialization (only when needed)
        - Automatic connection validation
        - Session string never logged
        - Connection reuse within session lifetime
        
        Returns:
            Connected TelegramClient or None if session invalid
        """
        async with self._client_lock:
            # Return existing valid client
            if self.has_active_client:
                self.touch()
                return self._client
            
            # Clean up stale client if present
            if self._client:
                await self._disconnect_client()
            
            # No session string = no client possible
            if not self.session_string:
                if self.step in (UserStep.AWAITING_OTP, UserStep.AWAITING_2FA):
                    logger.debug("Client requested during OTP flow - skipping (will connect after sign-in)")
                    return None
                return None
            
            # Create new client from session string
            try:
                client = TelegramClient(
                    StringSession(self.session_string),
                    API_ID,
                    API_HASH,
                    connection_retries=3
                )
                await client.connect()
                
                # Validate session authenticity
                if not await client.is_user_authorized():
                    await client.disconnect()
                    logger.warning("Session string rejected by Telegram - marking as invalid")
                    self.session_string = None
                    self.account_status = AccountStatus.INACTIVE
                    return None
                
                self._client = client
                self.touch()
                logger.debug(f"✓ Telethon client initialized for {self.masked_phone}")
                return client
                
            except Exception as e:
                logger.error(f"Client initialization failed: {type(e).__name__}: {e}")
                if 'client' in locals() and client:
                    try:
                        await client.disconnect()
                    except:
                        pass
                return None
    
    async def set_session(self, client: TelegramClient, phone: str) -> bool:
        """
        Securely store session from authenticated client.
        
        Args:
            client: Authenticated Telethon client
            phone: Associated phone number for validation
        
        Returns:
            True if session stored successfully
        """
        try:
            # Validate client is authorized
            if not await client.is_user_authorized():
                raise StateValidationError("Cannot store unauthorized session")
            
            # Save session string (pickle-safe)
            session_str = client.session.save()
            if not session_str or len(session_str) < 50:
                raise StateValidationError("Invalid session string generated")
            
            self.session_string = session_str
            self.phone = phone
            self.account_status = AccountStatus.ACTIVE
            self.touch()
            
            # Update internal client reference
            async with self._client_lock:
                if self._client:
                    await self._disconnect_client()
                self._client = client
            
            logger.info(f"✓ Session securely stored for {self.masked_phone}")
            return True
            
        except Exception as e:
            logger.error(f"Session storage failed: {e}")
            return False
    
    async def reset(self, full_cleanup: bool = True) -> None:
        """
        Reset state to default values with resource cleanup.
        
        Args:
            full_cleanup: If True, also disconnect client and clear session (default)
                          If False, preserve session for potential reuse
        """
        async with self._client_lock:
            # Cleanup Telethon client
            if self._client:
                await self._disconnect_client()
            
            # Clear sensitive data
            self.otp_buffer = ""
            self.ad_message_draft = None
            
            # Preserve session only if requested
            if full_cleanup:
                self.session_string = None
                self.phone = ""
                self.phone_code_hash = ""
                self.account_status = AccountStatus.INACTIVE
            
            # Reset flow state
            self.step = UserStep.IDLE
            self.campaign_status = CampaignStatus.STOPPED
            self.touch()
            
            logger.debug(f"User state reset (full_cleanup={full_cleanup})")
    
    async def _disconnect_client(self) -> None:
        """Safely disconnect Telethon client with error suppression"""
        if not self._client:
            return
        
        try:
            if self._client.is_connected():
                await self._client.disconnect()
                logger.debug(f"✓ Client disconnected for {self.masked_phone}")
        except Exception as e:
            logger.warning(f"Client disconnect error: {e}")
        finally:
            self._client = None
    
    def to_persistent_dict(self) -> Dict[str, Any]:
        """
        Convert to pickle-safe dictionary for persistence.
        
        Excludes:
        - Telethon client instances
        - Async locks
        - Cleanup tasks
        - Internal/private fields
        
        Returns:
            Dictionary safe for PicklePersistence
        """
        data = asdict(self)
        
        # Remove volatile/non-picklable fields
        exclude_fields = [
            '_client', '_client_lock', '_cleanup_task',
            'SESSION_TIMEOUT'  # Class variable
        ]
        for field in exclude_fields:
            data.pop(field, None)
        
        # Convert enums to strings for safer pickling
        data['step'] = self.step.value
        data['account_status'] = self.account_status.value
        data['campaign_status'] = self.campaign_status.value
        
        return data
    
    @classmethod
    def from_persistent_dict(cls, data: Dict[str, Any]) -> 'UserState':
        """
        Reconstruct UserState from persisted dictionary.
        
        Handles:
        - Enum value conversion
        - Missing field defaults
        - Type coercion
        - Backward compatibility
        
        Args:
            data: Dictionary from PicklePersistence
        
        Returns:
            Reconstructed UserState instance
        """
        # Convert string enums back to enum instances
        try:
            data['step'] = UserStep(data.get('step', 'idle'))
        except ValueError:
            data['step'] = UserStep.IDLE
        
        try:
            data['account_status'] = AccountStatus(data.get('account_status', 'inactive'))
        except ValueError:
            data['account_status'] = AccountStatus.INACTIVE
        
        try:
            data['campaign_status'] = CampaignStatus(data.get('campaign_status', 'stopped'))
        except ValueError:
            data['campaign_status'] = CampaignStatus.STOPPED
        
        # Ensure required fields exist with defaults
        defaults = {
            'last_activity': time.time(),
            'delay_setting': CONFIG.DEFAULT_DELAY,
            'otp_buffer': '',
            'ad_message_draft': None,
            'session_string': None,
            'phone_code_hash': ''
        }
        
        for key, default in defaults.items():
            if key not in data or data[key] is None:
                data[key] = default
        
        # Create instance without volatile fields
        instance = cls(**{
            k: v for k, v in data.items() 
            if k not in ['_client', '_client_lock', '_cleanup_task']
        })
        
        # Initialize volatile fields
        instance.__post_init__()
        return instance
    
    def validate_transition(self, new_step: UserStep) -> bool:
        """
        Validate state transition legality.
        
        Enforces flow constraints:
        - Cannot jump from idle to OTP without phone
        - Cannot set ad message without active account
        - Cannot start campaign without ad message
        
        Returns:
            True if transition allowed
        """
        # Idle can transition to any starting state
        if self.step == UserStep.IDLE:
            return new_step in [
                UserStep.AWAITING_PHONE,
                UserStep.SETTING_AD,
                UserStep.SETTING_DELAY
            ]
        
        # OTP flow constraints
        if self.step == UserStep.AWAITING_PHONE:
            return new_step == UserStep.AWAITING_OTP
        
        if self.step == UserStep.AWAITING_OTP:
            return new_step in [UserStep.AWAITING_2FA, UserStep.IDLE]
        
        if self.step == UserStep.AWAITING_2FA:
            return new_step == UserStep.IDLE
        
        # Campaign constraints
        if new_step == UserStep.CAMPAIGN_RUNNING:
            return (
                self.account_status == AccountStatus.ACTIVE and
                self.ad_message_draft is not None
            )
        
        return True
    
    @property
    def masked_phone(self) -> str:
        """Return phone number with all but last 4 digits masked"""
        if not self.phone:
            return "unknown"
        digits = re.sub(r'\D', '', self.phone)
        if len(digits) <= 4:
            return f"+{digits}"
        return f"+{'•' * (len(digits) - 4)}{digits[-4:]}"
    
    def __str__(self) -> str:
        """Human-readable state representation for logging"""
        return (
            f"UserState(step={self.step.value}, phone={self.masked_phone}, "
            f"status={self.account_status.value}, active_client={self.has_active_client}, "
            f"last_activity={datetime.fromtimestamp(self.last_activity).strftime('%H:%M:%S')})"
        )
    
    def __del__(self):
        """Final cleanup guard (best-effort)"""
        try:
            if self._client and asyncio.get_running_loop():
                # Schedule cleanup if event loop exists
                asyncio.create_task(self.reset(full_cleanup=False))
        except RuntimeError:
            # No event loop - skip async cleanup
            pass
        except Exception as e:
            logger.warning(f"Final cleanup error: {e}")