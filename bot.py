import asyncio
import logging
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, List, Set
from dataclasses import dataclass, field
from enum import Enum

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import BadRequest, Forbidden, RetryAfter

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.channels import GetChannelsRequest, GetFullChannelRequest
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerChannel, Channel
from telethon.errors import (
    SessionPasswordNeededError, 
    PhoneCodeInvalidError,
    FloodWaitError,
    AuthKeyUnregisteredError,
    UserBannedInChannelError,
    ChatWriteForbiddenError,
    PeerFloodError
)

from motor.motor_asyncio import AsyncIOMotorClient

# --- Configuration ---
BOT_TOKEN = '8463982454:AAErd8EZswKgQ1BNF_r-N8iUH8HQcb293lQ'
API_ID = 22657083
API_HASH = 'd6186691704bd901bdab275ceaab88f3'
MONGO_URI = "mongodb+srv://bot627668:2bEJ56yJSu7vzLws@cluster0.qbw5van.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
BANNER_URL = "https://files.catbox.moe/zttfbe.jpg"

PROFILE_NAME = "Nexa Ads"
PROFILE_BIO = "🚀 Professional Telegram Marketing Automation | Managed by @nexacoders"

# Anti-flood configuration (safe defaults)MIN_DELAY = 5  # 5 minutes minimum (Telegram-safe)
MAX_MESSAGES_PER_HOUR = 1000  # Conservative limit to avoid bans
FLOOD_COOLDOWN = 3600  # 1 hour cooldown after flood error

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

db = AsyncIOMotorClient(MONGO_URI)["adimyze"]

class CampaignStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"

@dataclass
class UserState:
    step: str = "idle"
    phone: str = ""
    phone_code_hash: str = ""
    client: Optional[TelegramClient] = None
    buffer: str = ""
    delay: int = MIN_DELAY
    password_retry: int = 0

@dataclass
class BroadcastTask:
    task: asyncio.Task
    status: CampaignStatus = CampaignStatus.IDLE
    last_sent: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    messages_sent: int = 0
    flood_cooldown_until: Optional[datetime] = None
    active_accounts: List[str] = field(default_factory=list)

# Global state management
user_states: Dict[int, UserState] = {}
campaign_tasks: Dict[int, BroadcastTask] = {}
active_sessions: Dict[str, TelegramClient] = {}  # phone -> client

# --- SAFE MESSAGE HANDLING ---
async def safe_edit_or_send(query, text, reply_markup=None):
    """Intelligently handle message edits for both text and media messages"""
    try:
        if query.message.photo:
            await query.edit_message_caption(caption=text, reply_markup=reply_markup)
        else:            await query.edit_message_text(text=text, reply_markup=reply_markup)
    except BadRequest as e:
        error_msg = str(e).lower()
        if "message is not modified" in error_msg:
            return
        elif "not found" in error_msg or "can't be edited" in error_msg:
            if query.message.photo:
                await query.message.reply_photo(photo=BANNER_URL, caption=text, reply_markup=reply_markup)
            else:
                await query.message.reply_text(text=text, reply_markup=reply_markup)
            try:
                await query.message.delete()
            except Exception:
                pass
        else:
            raise

# --- ENHANCED OTP UI (Real App Experience) ---
def kb_otp(user_id: int, error: str = "") -> InlineKeyboardMarkup:
    state = user_states.get(user_id, UserState())
    digits = list(state.buffer.ljust(5, "○"))[:5]

    # Modern 3x4 keypad layout like real phones
    keypad = [
        [InlineKeyboardButton(f"Current: {' '.join(digits)}", callback_data="otp_display")],
        [InlineKeyboardButton("1", callback_data="otp|1"),
         InlineKeyboardButton("2", callback_data="otp|2"),
         InlineKeyboardButton("3", callback_data="otp|3")],
        [InlineKeyboardButton("4", callback_data="otp|4"),
         InlineKeyboardButton("5", callback_data="otp|5"),
         InlineKeyboardButton("6", callback_data="otp|6")],
        [InlineKeyboardButton("7", callback_data="otp|7"),
         InlineKeyboardButton("8", callback_data="otp|8"),
         InlineKeyboardButton("9", callback_data="otp|9")],
        [InlineKeyboardButton("⌫", callback_data="otp|back"),
         InlineKeyboardButton("0", callback_data="otp|0"),
         InlineKeyboardButton("❌ Cancel", callback_data="otp|cancel")],
    ]

    if error:
        keypad.insert(0, [InlineKeyboardButton(f"⚠️ {error}", callback_data="otp_error")])

    keypad.append([InlineKeyboardButton("Show Code", url="tg://openmessage?user_id=777000")])

    return InlineKeyboardMarkup(keypad)

# --- KEYBOARDS ---
def kb_start() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Dashboard", callback_data="nav|dashboard")],        [InlineKeyboardButton("Updates", url="https://t.me/testttxs"),
         InlineKeyboardButton("Support", url="https://t.me/nexaxoders")],
        [InlineKeyboardButton("How to Use", callback_data="nav|howto")],
        [InlineKeyboardButton("Powered by", url="https://t.me/nexacoders")]
    ])

def kb_dashboard(user_id: int) -> InlineKeyboardMarkup:
    campaign_active = user_id in campaign_tasks and campaign_tasks[user_id].status == CampaignStatus.RUNNING

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Accounts", callback_data="acc|add"),
         InlineKeyboardButton("My Accounts", callback_data="acc|list|0")],
        [InlineKeyboardButton("Set Ad Message", callback_data="ad|set"),
         InlineKeyboardButton("Set Time Interval", callback_data="delay|nav")],
        [InlineKeyboardButton("Start Ads▶️" if not campaign_active else "Stop Ads⏸️", 
                             callback_data="camp|start" if not campaign_active else "camp|pause"),
         InlineKeyboardButton("⏹️ Stop Broadcast", callback_data="camp|stop")],
        [InlineKeyboardButton("🗑️ Delete Accounts", callback_data="acc|del"),
         InlineKeyboardButton("Analytics", callback_data="stat|main")],
        [InlineKeyboardButton("Auto Reply", callback_data="feature|auto"),
         InlineKeyboardButton("Back", callback_data="nav|start")]
    ])

def kb_delay(current_delay: int = MIN_DELAY) -> InlineKeyboardMarkup:
    def get_emoji(sec: int) -> str:
        return "🔴" if sec < 600 else "🟡" if sec < 1200 else "🟢"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"5 sec {get_emoji(05)} ⚠️ Risky", callback_data="setdelay|300"),
         InlineKeyboardButton(f"10 min {get_emoji(600)} ✅ Recommended", callback_data="setdelay|600")],
        [InlineKeyboardButton(f"20 min {get_emoji(1200)} 🔒 Safest", callback_data="setdelay|1200")],
        [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="nav|dashboard")]
    ])

def kb_accounts(accounts: List[dict], page: int = 0) -> InlineKeyboardMarkup:
    buttons = []
    page_size = 5
    start = page * page_size
    end = start + page_size
    page_accounts = accounts[start:end]

    for acc in page_accounts:
        status = "🟢" if acc.get("active", False) else "🔴"
        phone = acc["phone"]
        display = f"{status} ••••{phone[-4:]}"
        buttons.append([InlineKeyboardButton(display, callback_data=f"acc|detail|{acc['_id']}")])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"acc|list|{page-1}"))    if end < len(accounts):
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"acc|list|{page+1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton("🔙 Back to Dashboard", callback_data="nav|dashboard")])
    return InlineKeyboardMarkup(buttons)

def kb_account_detail(acc_id: str, phone: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ Delete Account", callback_data=f"acc|delete|{acc_id}")],
        [InlineKeyboardButton("Back", callback_data="acc|list|0")],
        [InlineKeyboardButton("Dashboard", callback_data="nav|dashboard")]
    ])

def kb_confirm_delete(acc_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, Delete", callback_data=f"acc|confirm_del|{acc_id}"),
         InlineKeyboardButton("❌ Cancel", callback_data="nav|dashboard")]
    ])

def kb_ad_message(current_msg: str = "") -> InlineKeyboardMarkup:
    if current_msg:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("Current Ad Message:", callback_data="noop")],
            [InlineKeyboardButton(current_msg[:30] + ("..." if len(current_msg) > 30 else ""), callback_data="noop")],
            [InlineKeyboardButton("Tips for effective ads:", callback_data="noop")],
            [InlineKeyboardButton("•Keep it concise and engaging", callback_data="noop")],
            [InlineKeyboardButton("•Use premium emojis for flair", callback_data="noop")],
            [InlineKeyboardButton("•Include clear call-to-action", callback_data="noop")],
            [InlineKeyboardButton("•Avoid excessive caps or spam words", callback_data="noop")],
            [InlineKeyboardButton("Send your ad message now:", callback_data="noop")],
            [InlineKeyboardButton("Dashboard", callback_data="nav|dashboard")]
        ])
    else:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("Tips for effective ads:", callback_data="noop")],
            [InlineKeyboardButton("•Keep it concise and engaging", callback_data="noop")],
            [InlineKeyboardButton("•Use premium emojis for flair", callback_data="noop")],
            [InlineKeyboardButton("•Include clear call-to-action", callback_data="noop")],
            [InlineKeyboardButton("•Avoid excessive caps or spam words", callback_data="noop")],
            [InlineKeyboardButton("Send your ad message now:", callback_data="noop")],
            [InlineKeyboardButton("Dashboard", callback_data="nav|dashboard")]
        ])

def kb_analytics() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Detailed Report", callback_data="stat|detail")],
        [InlineKeyboardButton("Dashboard", callback_data="nav|dashboard")]
    ])
def kb_analytics_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Detailed Report", callback_data="stat|detail")],
        [InlineKeyboardButton("Dashboard", callback_data="nav|dashboard")]
    ])

def kb_detailed_report() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Analytics", callback_data="stat|main")],
        [InlineKeyboardButton("Dashboard", callback_data="nav|dashboard")]
    ])

# --- BROADCAST ENGINE (Production-Ready) ---
class BroadcastEngine:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.running = False
        self.accounts: List[dict] = []
        self.ad_text: str = ""
        self.delay: int = MIN_DELAY
        self.sent_count = 0
        self.failed_count = 0
        self.last_flood_error: Optional[datetime] = None
        self.active_sessions: Dict[str, TelegramClient] = {}
        self.target_groups: List[Channel] = []
        self.account_rotation_index = 0

    async def initialize(self) -> bool:
        """Load campaign configuration from database"""
        try:
            # Load user settings
            user_doc = await db.users.find_one({"user_id": str(self.user_id)})
            self.delay = user_doc.get("delay", MIN_DELAY) if user_doc else MIN_DELAY

            # Load ad message
            ad_doc = await db.ads.find_one({"user_id": str(self.user_id)})
            if not ad_doc or not ad_doc.get("text"):
                logger.warning(f"User {self.user_id} has no ad message configured")
                return False
            self.ad_text = ad_doc["text"]

            # Load active accounts
            self.accounts = await db.accounts.find({
                "user_id": self.user_id, 
                "active": True
            }).to_list(None)

            if not self.accounts:
                logger.warning(f"User {self.user_id} has no active accounts")                return False

            # Initialize Telethon sessions
            for acc in self.accounts:
                try:
                    client = TelegramClient(
                        StringSession(acc["session"]), 
                        API_ID, 
                        API_HASH,
                        connection_retries=3
                    )
                    await client.connect()

                    if not await client.is_user_authorized():
                        logger.warning(f"Session expired for {acc['phone']}")
                        await db.accounts.update_one(
                            {"_id": acc["_id"]},
                            {"$set": {"active": False}}
                        )
                        continue

                    # Update profile to maintain consistency
                    try:
                        await client(UpdateProfileRequest(
                            first_name=PROFILE_NAME,
                            about=PROFILE_BIO
                        ))
                    except Exception as e:
                        logger.warning(f"Profile update failed for {acc['phone']}: {e}")

                    self.active_sessions[acc["phone"]] = client
                    logger.info(f"Initialized session for {acc['phone']}")
                except Exception as e:
                    logger.error(f"Failed to initialize session for {acc['phone']}: {e}")
                    await db.accounts.update_one(
                        {"_id": acc["_id"]},
                        {"$set": {"active": False}}
                    )

            if not self.active_sessions:
                logger.error(f"No valid sessions available for user {self.user_id}")
                return False

            # Discover target groups (only groups where we can send messages)
            await self._discover_target_groups()

            if not self.target_groups:
                logger.warning(f"No target groups found for user {self.user_id}")
                return False
            self.running = True
            logger.info(f"Broadcast engine initialized for user {self.user_id} with {len(self.active_sessions)} accounts and {len(self.target_groups)} target groups")
            return True

        except Exception as e:
            logger.exception(f"Broadcast initialization failed for user {self.user_id}: {e}")
            return False

    async def _discover_target_groups(self):
        """Discover groups/channels where the account can send messages"""
        sample_client = next(iter(self.active_sessions.values()))

        try:
            # Get all dialogs (chats, groups, channels)
            dialogs = await sample_client.get_dialogs(limit=100)

            for dialog in dialogs:
                entity = dialog.entity

                # Skip private chats and bots
                if not hasattr(entity, 'broadcast') and not hasattr(entity, 'megagroup'):
                    continue

                # Skip broadcast channels (can't send messages there)
                if hasattr(entity, 'broadcast') and entity.broadcast:
                    continue

                # Check if we can actually send messages
                try:
                    if hasattr(entity, 'megagroup') and entity.megagroup:
                        # It's a supergroup
                        await sample_client.get_permissions(entity, await sample_client.get_me())
                    self.target_groups.append(entity)
                except (UserBannedInChannelError, ChatWriteForbiddenError):
                    continue
                except Exception as e:
                    logger.debug(f"Skipping group {entity.title}: {e}")

            logger.info(f"Discovered {len(self.target_groups)} target groups for broadcasting")

        except Exception as e:
            logger.exception(f"Group discovery failed: {e}")

    async def _get_next_account(self) -> Optional[TelegramClient]:
        """Rotate through accounts to distribute load and avoid detection"""
        if not self.active_sessions:
            return None

        phones = list(self.active_sessions.keys())
        client = self.active_sessions[phones[self.account_rotation_index]]        self.account_rotation_index = (self.account_rotation_index + 1) % len(phones)
        return client

    async def _safe_send(self, client: TelegramClient, group: Channel) -> bool:
        """Send message with flood protection and error handling"""
        try:
            # Anti-flood: Check hourly message limit per account
            now = datetime.now(timezone.utc)
            account_stats = await db.broadcast_stats.find_one({
                "user_id": self.user_id,
                "phone": next(p for p, c in self.active_sessions.items() if c == client),
                "hour": now.strftime("%Y-%m-%d-%H")
            }) or {"count": 0}

            if account_stats["count"] >= MAX_MESSAGES_PER_HOUR:
                logger.warning(f"Hourly limit reached for account. Skipping send.")
                return False

            # Send message
            await client.send_message(group, self.ad_text)

            # Update stats
            await db.broadcast_stats.update_one(
                {
                    "user_id": self.user_id,
                    "phone": next(p for p, c in self.active_sessions.items() if c == client),
                    "hour": now.strftime("%Y-%m-%d-%H")
                },
                {"$inc": {"count": 1, "total": 1}},
                upsert=True
            )

            # Update campaign stats
            await db.campaigns.update_one(
                {"user_id": self.user_id, "status": "running"},
                {"$inc": {"messages_sent": 1}, "$set": {"last_sent": now}},
                upsert=True
            )

            self.sent_count += 1
            logger.info(f"Sent message to {group.title} via {client}")
            return True

        except (FloodWaitError, PeerFloodError) as e:
            wait_time = getattr(e, 'seconds', FLOOD_COOLDOWN)
            logger.warning(f"Flood protection triggered. Waiting {wait_time}s")
            self.last_flood_error = datetime.now(timezone.utc) + timedelta(seconds=wait_time)

            # Deactivate account temporarily
            phone = next(p for p, c in self.active_sessions.items() if c == client)            await db.accounts.update_one(
                {"user_id": self.user_id, "phone": phone},
                {"$set": {"flood_cooldown_until": datetime.now(timezone.utc) + timedelta(seconds=wait_time)}}
            )

            # Global campaign cooldown
            await db.campaigns.update_one(
                {"user_id": self.user_id},
                {"$set": {"flood_cooldown_until": datetime.now(timezone.utc) + timedelta(seconds=wait_time)}}
            )

            self.failed_count += 1
            return False

        except (UserBannedInChannelError, ChatWriteForbiddenError) as e:
            logger.warning(f"Cannot send to {group.title}: {e}")
            self.failed_count += 1
            return False

        except Exception as e:
            logger.error(f"Send failed to {group.title}: {e}")
            self.failed_count += 1
            return False

    async def run_cycle(self):
        """Execute one broadcast cycle across all accounts and groups"""
        if not self.running or not self.target_groups:
            return False

        # Check global flood cooldown
        campaign = await db.campaigns.find_one({"user_id": self.user_id})
        if campaign and campaign.get("flood_cooldown_until"):
            if datetime.now(timezone.utc) < campaign["flood_cooldown_until"]:
                logger.info("Global flood cooldown active. Skipping cycle.")
                return True

        # Rotate through target groups
        for group in self.target_groups:
            if not self.running:
                break

            # Get next available account (skip those in flood cooldown)
            client = await self._get_next_account()
            if not client:
                logger.warning("No available accounts for broadcasting")
                break

            # Check account-specific flood cooldown
            phone = next(p for p, c in self.active_sessions.items() if c == client)
            account = await db.accounts.find_one({"user_id": self.user_id, "phone": phone})            if account and account.get("flood_cooldown_until"):
                if datetime.now(timezone.utc) < account["flood_cooldown_until"]:
                    continue  # Skip this account

            # Send message with anti-flood protection
            success = await self._safe_send(client, group)

            # Enforce safe delay between messages (per Telegram guidelines)
            await asyncio.sleep(max(self.delay, MIN_DELAY))

        return self.running

    async def stop(self):
        """Gracefully stop broadcast and cleanup resources"""
        self.running = False

        # Disconnect all clients
        for phone, client in self.active_sessions.items():
            try:
                await client.disconnect()
                logger.info(f"Disconnected session for {phone}")
            except Exception as e:
                logger.error(f"Failed to disconnect {phone}: {e}")

        self.active_sessions.clear()

    async def get_stats(self) -> dict:
        """Get current broadcast statistics"""
        campaigns = await db.campaigns.find_one({"user_id": self.user_id}) or {}
        total_sent = campaigns.get("messages_sent", 0)
        total_failed = campaigns.get("messages_failed", 0)
        
        total_broadcasts = total_sent + total_failed
        success_rate = (total_sent / total_broadcasts * 100) if total_broadcasts > 0 else 0
        
        return {
            "broadcast_cycles_completed": campaigns.get("cycles_completed", 0),
            "messages_sent": total_sent,
            "failed_sends": total_failed,
            "logger_failures": campaigns.get("logger_failures", 0),
            "active_accounts": len(self.active_sessions),
            "avg_delay": self.delay,
            "success_rate": success_rate
        }

# --- HANDLERS ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    welcome_text = (        "╰_╯ @NexaCoders Ads DASHBOARD\n\n"
        "•Hosted Accounts: 0/5\n"
        "•Ad Message: Not Set ❌\n"
        "•Cycle Interval: 300s\n"
        "•Advertising Status: Stopped ⏹️\n\n"
        "╰_╯Choose an action below to continue"
    )
    
    # Check if user has ad message
    ad_doc = await db.ads.find_one({"user_id": str(user_id)})
    if ad_doc and ad_doc.get("text"):
        welcome_text = welcome_text.replace("•Ad Message: Not Set ❌", "•Ad Message: Set ✅")
    
    # Check if campaign is running
    campaign = await db.campaigns.find_one({"user_id": user_id, "status": "running"})
    if campaign:
        welcome_text = welcome_text.replace("•Advertising Status: Stopped ⏹️", "•Advertising Status: Running ▶️")
    
    # Count active accounts
    accounts = await db.accounts.count_documents({"user_id": user_id, "active": True})
    welcome_text = welcome_text.replace("•Hosted Accounts: 0/5", f"•Hosted Accounts: {accounts}/5")
    
    await update.message.reply_text(welcome_text, reply_markup=kb_start())

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data.startswith("nav|"):
        nav_action = data.split("|")[1]
        if nav_action == "dashboard":
            # Get dashboard info
            accounts_count = await db.accounts.count_documents({"user_id": user_id, "active": True})
            
            # Check ad message
            ad_doc = await db.ads.find_one({"user_id": str(user_id)})
            ad_status = "Set ✅" if ad_doc and ad_doc.get("text") else "Not Set ❌"
            
            # Check campaign status
            campaign = await db.campaigns.find_one({"user_id": user_id})
            if campaign and campaign.get("status") == "running":
                status = "Running ▶️"
            elif campaign and campaign.get("status") == "paused":
                status = "Paused ⏸️"
            else:
                status = "Stopped ⏹️"
                            delay = campaign.get("delay", 300) if campaign else 300
            
            dashboard_text = (
                "╰_╯ @NexaCoders Ads DASHBOARD\n\n"
                f"•Hosted Accounts: {accounts_count}/5\n"
                f"•Ad Message: {ad_status}\n"
                f"•Cycle Interval: {delay}s\n"
                f"•Advertising Status: {status}\n\n"
                "╰_╯Choose an action below to continue"
            )
            
            await safe_edit_or_send(query, dashboard_text, reply_markup=kb_dashboard(user_id))
            
        elif nav_action == "start":
            welcome_text = (
                "╰_╯ @NexaCoders Ads DASHBOARD\n\n"
                "•Hosted Accounts: 0/5\n"
                "•Ad Message: Not Set ❌\n"
                "•Cycle Interval: 300s\n"
                "•Advertising Status: Stopped ⏹️\n\n"
                "╰_╯Choose an action below to continue"
            )
            
            # Check if user has ad message
            ad_doc = await db.ads.find_one({"user_id": str(user_id)})
            if ad_doc and ad_doc.get("text"):
                welcome_text = welcome_text.replace("•Ad Message: Not Set ❌", "•Ad Message: Set ✅")
            
            # Check if campaign is running
            campaign = await db.campaigns.find_one({"user_id": user_id, "status": "running"})
            if campaign:
                welcome_text = welcome_text.replace("•Advertising Status: Stopped ⏹️", "•Advertising Status: Running ▶️")
            
            # Count active accounts
            accounts = await db.accounts.count_documents({"user_id": user_id, "active": True})
            welcome_text = welcome_text.replace("•Hosted Accounts: 0/5", f"•Hosted Accounts: {accounts}/5")
            
            await safe_edit_or_send(query, welcome_text, reply_markup=kb_start())
    
    elif data.startswith("acc|"):
        action_parts = data.split("|")
        action = action_parts[1]
        
        if action == "add":
            await safe_edit_or_send(
                query, 
                "╰_╯HOST NEW ACCOUNT\n\n"
                "Secure Account Hosting\n\n"
                "Enter your phone number with country code:\n\n"
                "Example: +1234567890\n\n"                "Your data is encrypted and secure",
                reply_markup=None
            )
            user_states[user_id] = UserState(step="waiting_phone")
        
        elif action == "list":
            page = int(action_parts[2]) if len(action_parts) > 2 else 0
            accounts = await db.accounts.find({"user_id": user_id}).to_list(None)
            await safe_edit_or_send(
                query,
                f"Your Accounts ({len(accounts)} total):",
                reply_markup=kb_accounts(accounts, page)
            )
        
        elif action == "del":
            accounts = await db.accounts.find({"user_id": user_id}).to_list(None)
            if not accounts:
                await safe_edit_or_send(query, "No accounts to delete!", reply_markup=kb_dashboard(user_id))
            else:
                await safe_edit_or_send(
                    query,
                    f"Select account to delete ({len(accounts)} available):",
                    reply_markup=kb_accounts(accounts, 0)
                )
    
    elif data.startswith("otp|"):
        action = data.split("|")[1]
        
        if action == "cancel":
            await safe_edit_or_send(query, "Process Cancelled.", reply_markup=kb_dashboard(user_id))
            if user_id in user_states:
                del user_states[user_id]
        
        elif action == "back":
            state = user_states.get(user_id)
            if state and len(state.buffer) > 0:
                state.buffer = state.buffer[:-1]
                await safe_edit_or_send(query.message.text, reply_markup=kb_otp(user_id))
        
        elif action.isdigit():
            state = user_states.get(user_id)
            if state and len(state.buffer) < 5:
                state.buffer += action
                await safe_edit_or_send(query.message.text, reply_markup=kb_otp(user_id))
                
                # If OTP is complete
                if len(state.buffer) == 5:
                    await safe_edit_or_send(
                        query,
                        "Verifying OTP...",                        reply_markup=None
                    )
                    
                    try:
                        # Verify OTP
                        await state.client.sign_in(state.phone, state.buffer)
                        
                        # Save session
                        session_string = state.client.session.save()
                        
                        # Save to database
                        await db.accounts.insert_one({
                            "user_id": user_id,
                            "phone": state.phone,
                            "session": session_string,
                            "active": True,
                            "added_at": datetime.now(timezone.utc)
                        })
                        
                        # Update profile
                        await state.client(UpdateProfileRequest(
                            first_name=PROFILE_NAME,
                            about=PROFILE_BIO
                        ))
                        
                        await state.client.disconnect()
                        
                        await safe_edit_or_send(
                            query,
                            "Account Successfully added!✅\n\n"
                            f"Phone: {state.phone}\n"
                            "╰_╯Your account is ready for broadcasting!\n"
                            "Note: Profile bio and name will be updated during the first broadcast, you change it if you want.",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("[ Dashboard ]", callback_data="nav|dashboard")]
                            ])
                        )
                        
                        del user_states[user_id]
                        
                    except PhoneCodeInvalidError:
                        state.buffer = ""
                        await safe_edit_or_send(
                            query,
                            "Invalid OTP. Please try again.",
                            reply_markup=kb_otp(user_id)
                        )
                    except Exception as e:
                        logger.error(f"OTP verification failed: {e}")
                        await safe_edit_or_send(                            query,
                            f"Verification failed: {str(e)}",
                            reply_markup=kb_otp(user_id)
                        )
    
    elif data.startswith("ad|"):
        action = data.split("|")[1]
        
        if action == "set":
            # Get current ad message
            ad_doc = await db.ads.find_one({"user_id": str(user_id)})
            current_msg = ad_doc["text"] if ad_doc and ad_doc.get("text") else ""
            
            if current_msg:
                msg_text = (
                    "╰_╯ SET YOUR AD MESSAGE\n\n"
                    f"Current Ad Message: {current_msg}\n\n"
                    "Tips for effective ads:\n"
                    "•Keep it concise and engaging\n"
                    "•Use premium emojis for flair\n"
                    "•Include clear call-to-action\n"
                    "•Avoid excessive caps or spam words\n\n"
                    "Send your ad message now:"
                )
            else:
                msg_text = (
                    "╰_╯ SET YOUR AD MESSAGE\n\n"
                    "Tips for effective ads:\n"
                    "•Keep it concise and engaging\n"
                    "•Use premium emojis for flair\n"
                    "•Include clear call-to-action\n"
                    "•Avoid excessive caps or spam words\n\n"
                    "Send your ad message now:"
                )
            
            await safe_edit_or_send(query, msg_text, reply_markup=kb_ad_message(current_msg))
            user_states[user_id] = UserState(step="waiting_ad_message")
    
    elif data.startswith("stat|"):
        action = data.split("|")[1]
        
        if action == "main":
            # Get analytics data
            accounts_count = await db.accounts.count_documents({"user_id": user_id, "active": True})
            
            # Get campaign stats
            campaign = await db.campaigns.find_one({"user_id": user_id}) or {}
            cycles_completed = campaign.get("cycles_completed", 0)
            messages_sent = campaign.get("messages_sent", 0)
            failed_sends = campaign.get("messages_failed", 0)            logger_failures = campaign.get("logger_failures", 0)
            avg_delay = campaign.get("delay", 300)
            
            total_messages = messages_sent + failed_sends
            success_rate = (messages_sent / total_messages * 100) if total_messages > 0 else 0
            
            analytics_text = (
                "╰_╯@Tecxo ANALYTICS\n\n"
                f"Broadcast Cycles Completed: {cycles_completed}\n"
                f"Messages Sent: {messages_sent}\n"
                f"Failed Sends: {failed_sends}\n"
                f"Logger Failures: {logger_failures}\n"
                f"Active Accounts: {accounts_count}\n"
                f"Avg Delay: {avg_delay}s\n\n"
                f"Success Rate: {'▓' * int(success_rate/10)}{'░' * (10-int(success_rate/10))} {int(success_rate)}%"
            )
            
            await safe_edit_or_send(query, analytics_text, reply_markup=kb_analytics_main())
        
        elif action == "detail":
            # Get detailed report
            accounts_count = await db.accounts.count_documents({"user_id": user_id})
            active_accounts = await db.accounts.count_documents({"user_id": user_id, "active": True})
            inactive_accounts = accounts_count - active_accounts
            
            # Get campaign stats
            campaign = await db.campaigns.find_one({"user_id": user_id}) or {}
            total_sent = campaign.get("messages_sent", 0)
            total_failed = campaign.get("messages_failed", 0)
            total_broadcasts = total_sent + total_failed
            avg_delay = campaign.get("delay", 300)
            
            # Get current date
            current_date = datetime.now().strftime("%d/%m/%y")
            
            detail_text = (
                "╰_╯ DETAILED ANALYTICS REPORT:\n\n"
                f"Date: {current_date}\n"
                f"User ID: {user_id}\n\n"
                "Broadcast Stats:\n"
                f"- Total Sent: {total_sent}\n"
                f"- Total Failed: {total_failed}\n"
                f"- Total Broadcasts: {total_broadcasts}\n\n"
                "Logger Stats:\n"
                f"- Logger Failures: {campaign.get('logger_failures', 0)}\n"
                f"- Last Failure: {campaign.get('last_failure', 'None')}\n\n"
                "Account Stats:\n"
                f"- Total Accounts: {accounts_count}\n"
                f"- Active Accounts: {active_accounts} 🟢\n"
                f"- Inactive Accounts: {inactive_accounts} 🔴\n\n"                f"Current Delay: {avg_delay}s"
            )
            
            await safe_edit_or_send(query, detail_text, reply_markup=kb_detailed_report())

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    
    if state and state.step == "waiting_phone":
        phone_number = update.message.text.strip()
        
        # Validate phone number format
        if not re.match(r'^\+\d{10,15}$', phone_number):
            await update.message.reply_text(
                "Invalid phone number format. Please enter with country code (e.g., +1234567890)"
            )
            return
        
        # Create Telethon client
        client = TelegramClient(StringSession(""), API_ID, API_HASH)
        await client.connect()
        
        try:
            # Send OTP
            sent_code = await client.send_code_request(phone_number)
            
            # Store state
            state.phone = phone_number
            state.phone_code_hash = sent_code.phone_code_hash
            state.client = client
            state.step = "waiting_otp"
            state.buffer = ""
            
            # Show OTP interface
            otp_text = (
                f"⏳ Hold! We're trying to OTP...\n\n"
                f"Phone: {phone_number}\n"
                "Please wait a moment.\n\n"
                f"Fir\n\n"
                f"3 row ka ho\n\n"
                f"╰_╯ OTP sent to {phone_number}! ✅\n\n"
                "Enter the OTP using the keypad below\n"
                "Current: * * * * *\n"
                "Format: 12345 (no spaces needed)\n"
                "Valid for: 5 minutes"
            )
            
            await update.message.reply_text(otp_text, reply_markup=kb_otp(user_id))
                    except Exception as e:
            await client.disconnect()
            await update.message.reply_text(f"Error sending OTP: {str(e)}")
    
    elif state and state.step == "waiting_ad_message":
        ad_message = update.message.text
        
        # Save ad message to database
        await db.ads.update_one(
            {"user_id": str(user_id)},
            {"$set": {"text": ad_message, "updated_at": datetime.now(timezone.utc)}},
            upsert=True
        )
        
        # Update user state
        state.step = "idle"
        
        # Show confirmation
        confirm_text = (
            "╰_╯ SET YOUR AD MESSAGE\n\n"
            f"Current Ad Message: {ad_message}\n\n"
            "Tips for effective ads:\n"
            "•Keep it concise and engaging\n"
            "•Use premium emojis for flair\n"
            "•Include clear call-to-action\n"
            "•Avoid excessive caps or spam words\n\n"
            "Send your ad message now:"
        )
        
        await update.message.reply_text(confirm_text, reply_markup=kb_ad_message(ad_message))

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    logger.info("Bot started...")
    application.run_polling()

if __name__ == "__main__":
    main()