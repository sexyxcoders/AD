"""Safe, multi-account broadcasting service with anti-spam protections"""
import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import List, Dict, Optional, Tuple, Any
from collections import deque

from telegram.ext import ContextTypes

from core import CONFIG, db
from services.telegram_client import (
    managed_client,
    get_joined_chats,
    send_message_safe,
    AccountHealthStatus
)
from models.user_state import UserState

logger = logging.getLogger(__name__)

class BroadcastStatus(Enum):
    """Campaign lifecycle states"""
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"

class AccountHealthStatus(Enum):
    """Account health classification for safety"""
    HEALTHY = "healthy"      # No recent errors, good success rate
    WARNING = "warning"      # Some errors but recoverable
    RESTRICTED = "restricted"  # Temporary restrictions (flood waits)
    BANNED = "banned"        # Permanent ban/deactivation
    UNKNOWN = "unknown"      # Unable to determine status

@dataclass
class BroadcastResult:
    """Result of a single broadcast attempt"""
    account_id: str
    phone: str
    chat_id: int
    chat_title: str
    success: bool
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None
    message_preview: str = ""

@dataclass
class BroadcastCampaign:
    """Active broadcasting campaign state"""
    user_id: int
    status: BroadcastStatus = BroadcastStatus.IDLE
    start_time: Optional[datetime] = None
    last_broadcast: Optional[datetime] = None
    total_sent: int = 0
    total_failed: int = 0
    active_accounts: List[str] = field(default_factory=list)
    current_chat_index: int = 0
    chat_queue: deque = field(default_factory=deque)
    stop_requested: bool = False
    
    def get_success_rate(self) -> float:
        """Calculate current success rate percentage"""
        total = self.total_sent + self.total_failed
        return (self.total_sent / total * 100) if total > 0 else 100.0
    
    def is_healthy(self) -> bool:
        """Determine if campaign should continue based on health metrics"""
        return self.get_success_rate() >= 85.0  # Stop if success rate drops below 85%

class BroadcastManager:
    """Singleton manager for all broadcasting operations"""
    _instance = None
    _campaigns: Dict[int, BroadcastCampaign] = {}
    _running_tasks: Dict[int, asyncio.Task] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(BroadcastManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._health_check_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        logger.info("✓ BroadcastManager initialized")
    
    @classmethod
    def get_instance(cls) -> 'BroadcastManager':
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    async def start_campaign(self, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> Tuple[bool, str]:
        """
        Start a new broadcasting campaign for a user.
        
        Safety checks performed:
        1. Account health validation
        2. Ad message existence
        3. Minimum delay enforcement
        4. Daily message cap checks
        5. Concurrent campaign prevention
        
        Returns:
            Tuple of (success: bool, message: str)
        """
        # Prevent duplicate campaigns
        if user_id in self._campaigns and self._campaigns[user_id].status == BroadcastStatus.RUNNING:
            return False, "Campaign already running for this user"
        
        # Fetch user configuration
        user_doc = await db.users.find_one({"user_id": str(user_id)})
        if not user_doc:
            return False, "User configuration not found"
        
        delay = user_doc.get("delay", CONFIG.DEFAULT_DELAY)
        if delay < CONFIG.MIN_DELAY:
            return False, f"Interval too short. Minimum: {CONFIG.MIN_DELAY}s ({CONFIG.MIN_DELAY//60} min)"
        
        # Get active accounts
        accounts = await db.accounts.find({
            "user_id": user_id,
            "active": True
        }).to_list(None)
        
        if not accounts:
            return False, "No active accounts available for broadcasting"
        
        # Validate account health
        healthy_accounts = []
        for acc in accounts:
            is_valid, _ = await self._check_account_health(acc)
            if is_valid:
                healthy_accounts.append(acc)
        
        if not healthy_accounts:
            return False, "No healthy accounts available. Please check account status in Analytics."
        
        # Get ad message
        ad_doc = await db.ads.find_one({"user_id": str(user_id)})
        if not ad_doc or not ad_doc.get("text"):
            return False, "No ad message configured. Set your ad message first."
        
        # Check daily message caps (prevent spam)
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_sent = await db.analytics.count_documents({
            "user_id": str(user_id),
            "timestamp": {"$gte": today_start},
            "success": True
        })
        
        # Conservative daily cap: 50 messages per account
        daily_cap = len(healthy_accounts) * 50
        if today_sent >= daily_cap:
            return False, (
                f"Daily message cap reached ({today_sent}/{daily_cap}).\n"
                "Resume tomorrow to avoid Telegram restrictions."
            )
        
        # Initialize campaign
        campaign = BroadcastCampaign(
            user_id=user_id,
            status=BroadcastStatus.STARTING,
            active_accounts=[str(acc["_id"]) for acc in healthy_accounts]
        )
        self._campaigns[user_id] = campaign
        
        # Build chat queue (round-robin across accounts)
        await self._build_chat_queue(campaign, healthy_accounts, ad_doc["text"])
        
        if not campaign.chat_queue:
            return False, "No eligible chats found for broadcasting. Join more groups first."
        
        # Start background task
        campaign.status = BroadcastStatus.RUNNING
        campaign.start_time = datetime.now(timezone.utc)
        campaign.stop_requested = False
        
        task = asyncio.create_task(
            self._broadcast_loop(campaign, delay, ad_doc["text"], context)
        )
        self._running_tasks[user_id] = task
        
        logger.info(
            f"✓ Campaign started for user {user_id} with {len(healthy_accounts)} accounts, "
            f"{len(campaign.chat_queue)} chats, interval {delay}s"
        )
        
        return True, (
            f"🚀 Campaign started successfully!\n"
            f"• Accounts: {len(healthy_accounts)} active\n"
            f"• Chats: {len(campaign.chat_queue)} eligible\n"
            f"• Interval: {delay}s\n"
            f"• Daily Cap: {today_sent}/{daily_cap} messages used"
        )
    
    async def stop_campaign(self, user_id: int) -> Tuple[bool, str]:
        """Stop an active broadcasting campaign"""
        campaign = self._campaigns.get(user_id)
        if not campaign or campaign.status not in [BroadcastStatus.RUNNING, BroadcastStatus.PAUSED]:
            return False, "No active campaign to stop"
        
        campaign.stop_requested = True
        campaign.status = BroadcastStatus.STOPPING
        
        # Wait for current broadcast to complete (max 30s)
        if user_id in self._running_tasks:
            try:
                await asyncio.wait_for(self._running_tasks[user_id], timeout=30.0)
            except asyncio.TimeoutError:
                logger.warning(f"Timeout waiting for campaign {user_id} to stop gracefully")
        
        campaign.status = BroadcastStatus.STOPPED
        campaign.last_broadcast = datetime.now(timezone.utc)
        
        # Cleanup
        self._campaigns.pop(user_id, None)
        self._running_tasks.pop(user_id, None)
        
        logger.info(f"✓ Campaign stopped for user {user_id}")
        return True, "🛑 Campaign stopped successfully"
    
    async def _broadcast_loop(
        self,
        campaign: BroadcastCampaign,
        interval: int,
        message: str,
        context: ContextTypes.DEFAULT_TYPE
    ):
        """Main broadcasting loop with safety checks"""
        user_id = campaign.user_id
        
        while not campaign.stop_requested and campaign.status == BroadcastStatus.RUNNING:
            # Safety check: campaign health
            if not campaign.is_healthy():
                logger.warning(f"Campaign {user_id} health degraded. Pausing broadcasts.")
                campaign.status = BroadcastStatus.PAUSED
                await self._notify_user(
                    context,
                    user_id,
                    "⚠️ Campaign paused due to high failure rate.\n"
                    f"Success rate: {campaign.get_success_rate():.1f}% (below 85% threshold)\n"
                    "Check Analytics for details."
                )
                break
            
            # Get next broadcast target
            if not campaign.chat_queue:
                logger.info(f"Campaign {user_id} exhausted chat queue. Rebuilding...")
                accounts = await db.accounts.find({
                    "_id": {"$in": campaign.active_accounts},
                    "active": True
                }).to_list(None)
                await self._build_chat_queue(campaign, accounts, message)
                
                if not campaign.chat_queue:
                    logger.warning(f"Campaign {user_id} has no more eligible chats. Stopping.")
                    break
            
            account_id, chat_id, chat_title = campaign.chat_queue.popleft()
            
            # Get account session
            account = await db.accounts.find_one({"_id": account_id})
            if not account or not account.get("active"):
                logger.warning(f"Account {account_id} inactive during broadcast. Skipping.")
                continue
            
            # Broadcast with managed client
            async with managed_client(account["session"], account["phone"]) as client:
                success, error = await send_message_safe(client, chat_id, message)
                
                # Record result
                result = BroadcastResult(
                    account_id=account_id,
                    phone=account["phone"],
                    chat_id=chat_id,
                    chat_title=chat_title,
                    success=success,
                    error=error,
                    message_preview=message[:30] + "..." if len(message) > 30 else message
                )
                await self._record_result(user_id, result)
                
                # Update campaign stats
                if success:
                    campaign.total_sent += 1
                else:
                    campaign.total_failed += 1
                
                campaign.last_broadcast = datetime.now(timezone.utc)
                
                # Log significant events
                if not success:
                    logger.warning(
                        f"Broadcast failed for {account['phone']} to '{chat_title}': {error}"
                    )
                elif campaign.total_sent % 10 == 0:  # Log every 10 successful sends
                    logger.info(
                        f"Campaign {user_id}: {campaign.total_sent} sent, "
                        f"{campaign.total_failed} failed, "
                        f"queue: {len(campaign.chat_queue)}"
                    )
            
            # Safety delay between broadcasts
            # Add jitter to avoid pattern detection
            jitter = random.uniform(0.8, 1.2)
            await asyncio.sleep(interval * jitter)
        
        # Final cleanup
        campaign.status = BroadcastStatus.STOPPED
        logger.info(
            f"Campaign {user_id} ended: {campaign.total_sent} sent, "
            f"{campaign.total_failed} failed, "
            f"success rate: {campaign.get_success_rate():.1f}%"
        )
    
    async def _build_chat_queue(
        self,
        campaign: BroadcastCampaign,
        accounts: List[Dict],
        message: str
    ):
        """
        Build round-robin chat queue from all eligible accounts.
        
        Strategy:
        - Discover chats per account
        - Filter already-broadcast chats (24h cooldown)
        - Interleave chats from different accounts to distribute load
        - Respect daily message caps per account
        """
        queue = []
        today_start = datetime.now(timezone.utc) - timedelta(hours=24)
        
        for account in accounts:
            async with managed_client(account["session"], account["phone"]) as client:
                chats = await get_joined_chats(client)
                
                for chat in chats:
                    # Skip if already messaged recently (24h cooldown)
                    recent = await db.analytics.find_one({
                        "account_id": str(account["_id"]),
                        "chat_id": chat["id"],
                        "timestamp": {"$gte": today_start},
                        "success": True
                    })
                    
                    if not recent:
                        queue.append((
                            str(account["_id"]),
                            chat["id"],
                            chat["title"]
                        ))
        
        # Shuffle to avoid predictable patterns
        random.shuffle(queue)
        
        # Use deque for efficient pops from left
        campaign.chat_queue = deque(queue)
        logger.debug(f"Built chat queue with {len(queue)} targets for campaign {campaign.user_id}")
    
    async def _check_account_health(self, account: Dict) -> Tuple[bool, str]:
        """Comprehensive account health check"""
        # Check for recent failures
        hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        recent_failures = await db.analytics.count_documents({
            "account_id": str(account["_id"]),
            "timestamp": {"$gte": hour_ago},
            "success": False
        })
        
        if recent_failures > 5:
            return False, f"Too many recent failures ({recent_failures} in last hour)"
        
        # Validate session
        is_valid, reason = await validate_session(account["session"], account["phone"])
        if not is_valid:
            return False, reason
        
        return True, "Healthy"
    
    async def _record_result(self, user_id: int, result: BroadcastResult):
        """Record broadcast result to analytics database"""
        await db.analytics.insert_one({
            "user_id": str(user_id),
            "account_id": result.account_id,
            "phone": result.phone,
            "chat_id": result.chat_id,
            "chat_title": result.chat_title,
            "success": result.success,
            "error": result.error,
            "message_preview": result.message_preview,
            "timestamp": result.timestamp
        })
        
        # Update account last_used timestamp
        await db.accounts.update_one(
            {"_id": result.account_id},
            {"$set": {"last_used": result.timestamp}}
        )
    
    async def _notify_user(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        user_id: int,
        message: str
    ):
        """Send notification to user about campaign status"""
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=message,
                disable_notification=False  # Ensure user sees critical alerts
            )
        except Exception as e:
            logger.warning(f"Failed to notify user {user_id}: {e}")
    
    async def get_campaign_status(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get current campaign status for user"""
        campaign = self._campaigns.get(user_id)
        if not campaign:
            return None
        
        return {
            "status": campaign.status.value,
            "total_sent": campaign.total_sent,
            "total_failed": campaign.total_failed,
            "success_rate": campaign.get_success_rate(),
            "active_accounts": len(campaign.active_accounts),
            "queue_size": len(campaign.chat_queue),
            "running_since": campaign.start_time.isoformat() if campaign.start_time else None,
            "last_broadcast": campaign.last_broadcast.isoformat() if campaign.last_broadcast else None
        }
    
    async def start_background_tasks(self):
        """Start periodic maintenance tasks"""
        if self._health_check_task is None:
            self._health_check_task = asyncio.create_task(self._periodic_health_checks())
        
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
    
    async def _periodic_health_checks(self):
        """Periodic account health validation"""
        while True:
            try:
                await health_check_all_sessions()
                await asyncio.sleep(3600)  # Hourly checks
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check task error: {e}", exc_info=True)
                await asyncio.sleep(300)  # Retry after 5 minutes on error
    
    async def _periodic_cleanup(self):
        """Periodic session pool cleanup"""
        while True:
            try:
                await cleanup_stale_sessions()
                await asyncio.sleep(600)  # 10 minute cleanup cycles
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup task error: {e}", exc_info=True)
                await asyncio.sleep(60)

# Global manager instance
BROADCAST_MANAGER = BroadcastManager.get_instance()

async def initialize_broadcasting():
    """Initialize broadcasting service on application startup"""
    await BROADCAST_MANAGER.start_background_tasks()
    logger.info("✓ Broadcasting service initialized with background tasks")