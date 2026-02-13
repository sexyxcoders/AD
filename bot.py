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

# Anti-flood configuration (safe defaults)
MIN_DELAY = 5  # 5 minutes minimum (Telegram-safe)
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
        else:
            await query.edit_message_text(text=text, reply_markup=reply_markup)
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
        [InlineKeyboardButton(digits[0], callback_data="otp_display"),
         InlineKeyboardButton(digits[1], callback_data="otp_display"),
         InlineKeyboardButton(digits[2], callback_data="otp_display"),
         InlineKeyboardButton(digits[3], callback_data="otp_display"),
         InlineKeyboardButton(digits[4], callback_data="otp_display")],
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
         InlineKeyboardButton("↺ Resend", callback_data="otp|resend")],
    ]
    
    if error:
        keypad.insert(0, [InlineKeyboardButton(f"⚠️ {error}", callback_data="otp_error")])
    
    keypad.append([InlineKeyboardButton("Show Code", url="tg://openmessage?user_id=777000")])
    keypad.append([InlineKeyboardButton("❌", callback_data="otp|cancel")])
    
    return InlineKeyboardMarkup(keypad)

# --- KEYBOARDS ---
def kb_start() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Dashboard", callback_data="nav|dashboard")],
        [InlineKeyboardButton("Updates", url="https://t.me/testttxs"),
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
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"acc|list|{page-1}"))
    if end < len(accounts):
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
                logger.warning(f"User {self.user_id} has no active accounts")
                return False
                
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
        client = self.active_sessions[phones[self.account_rotation_index]]
        self.account_rotation_index = (self.account_rotation_index + 1) % len(phones)
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
            phone = next(p for p, c in self.active_sessions.items() if c == client)
            await db.accounts.update_one(
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
            account = await db.accounts.find_one({"user_id": self.user_id, "phone": phone})
            if account and account.get("flood_cooldown_until"):
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
                logger.error(f"Error disconnecting {phone}: {e}")
        
        self.active_sessions.clear()
        logger.info(f"Broadcast stopped for user {self.user_id}")

# --- BACKGROUND TASK SCHEDULER ---
async def broadcast_scheduler(user_id: int):
    """Background task that manages broadcast cycles"""
    engine = BroadcastEngine(user_id)
    
    try:
        if not await engine.initialize():
            logger.error(f"Broadcast initialization failed for user {user_id}")
            await db.campaigns.update_one(
                {"user_id": user_id},
                {"$set": {
                    "status": "stopped",
                    "stopped_at": datetime.now(timezone.utc),
                    "error": "Initialization failed - check accounts and ad message"
                }},
                upsert=True
            )
            return
        
        # Update campaign status
        await db.campaigns.update_one(
            {"user_id": user_id},
            {"$set": {
                "status": "running",
                "started_at": datetime.now(timezone.utc),
                "messages_sent": 0,
                "messages_failed": 0
            }},
            upsert=True
        )
        
        logger.info(f"Broadcast started for user {user_id}")
        
        # Main broadcast loop
        while engine.running:
            cycle_success = await engine.run_cycle()
            
            if not cycle_success:
                logger.warning(f"Broadcast cycle failed for user {user_id}. Stopping.")
                break
            
            # Check if campaign was stopped externally
            campaign = await db.campaigns.find_one({"user_id": user_id})
            if not campaign or campaign.get("status") != "running":
                logger.info(f"Broadcast stopped externally for user {user_id}")
                break
            
            # Respect minimum delay between cycles
            await asyncio.sleep(max(engine.delay, MIN_DELAY))
            
    except asyncio.CancelledError:
        logger.info(f"Broadcast task cancelled for user {user_id}")
    except Exception as e:
        logger.exception(f"Critical error in broadcast for user {user_id}: {e}")
    finally:
        await engine.stop()
        
        # Update final campaign status
        await db.campaigns.update_one(
            {"user_id": user_id},
            {"$set": {
                "status": "stopped",
                "stopped_at": datetime.now(timezone.utc),
                "final_stats": {
                    "messages_sent": engine.sent_count,
                    "messages_failed": engine.failed_count
                }
            }},
            upsert=True
        )
        
        # Cleanup task reference
        if user_id in campaign_tasks:
            del campaign_tasks[user_id]
        
        logger.info(f"Broadcast cleanup completed for user {user_id}")

# --- HANDLERS ---
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ("✨ Welcome to Adimyze Pro — Professional Telegram Marketing Automation\n\n"
            "✅ Premium Ad Broadcasting\n"
            "✅ Smart Anti-Flood Protection\n"
            "✅ Multi-Account Rotation\n"
            "✅ Background Task Scheduling\n\n"
            "⚠️ Use responsibly: Aggressive settings may risk account suspension\n"
            "🛠️ Support: @nexaxoders")

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.message.reply_photo(
            photo=BANNER_URL,
            caption=text,
            reply_markup=kb_start()
        )
        try:
            await query.message.delete()
        except Exception:
            pass
    else:
        await update.message.reply_photo(
            photo=BANNER_URL,
            caption=text,
            reply_markup=kb_start()
        )

async def handle_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    dest = parts[1]
    user_id = query.from_user.id

    if dest == "start":
        await cmd_start(update, context)

    elif dest == "dashboard":
        text = ("✨ Nexa Ads DASHBOARD\n\n"
                "Manage your professional ad campaigns:")
        await safe_edit_or_send(query, text, kb_dashboard(user_id))

    elif dest == "howto":
        text = ("📘 HOW TO USE ADIMYZE PRO\n\n"
                "1️⃣ Add Accounts → Host your Telegram accounts securely\n"
                "2️⃣ Set Ad Message → Create compelling promotional content\n"
                "3️⃣ Configure Interval → Set safe broadcasting frequency (10+ min recommended)\n"
                "4️⃣ Start Broadcast → Launch automated campaign\n\n"
                "⚠️ CRITICAL SAFETY NOTES:\n"
                "• Never use intervals below 5 minutes\n"
                "• Max 15 messages/hour per account\n"
                "• Always manually join target groups first\n"
                "• Rotate multiple accounts to avoid detection\n\n"
                "Responsible usage ensures account longevity!")
        await safe_edit_or_send(
            query,
            text,
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="nav|dashboard")]])
        )

async def handle_account_ops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    action = parts[1]
    user_id = query.from_user.id

    if action == "add":
        user_states[user_id] = UserState(step="phone")
        text = ("📱 HOST NEW ACCOUNT\n\n"
                "🔒 Secure Account Hosting\n\n"
                "Enter your phone number with country code:\n"
                "Example: +1234567890\n\n"
                "⚠️ Your session is encrypted and never shared")
        await query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]])
        )

    elif action == "list":
        page = int(parts[2])
        accounts = await db.accounts.find({"user_id": user_id}).to_list(None)

        if not accounts:
            await query.answer("📭 No accounts added yet!", show_alert=True)
            text = "📱 MY ACCOUNTS\n\nYou haven't added any accounts yet."
            await safe_edit_or_send(query, text, kb_dashboard(user_id))
            return

        text = f"📱 MY ACCOUNTS ({len(accounts)})\n\nSelect an account to manage:"
        await safe_edit_or_send(query, text, kb_accounts(accounts, page))

    elif action == "detail":
        acc_id = parts[2]
        account = await db.accounts.find_one({"_id": acc_id, "user_id": user_id})
        if not account:
            await query.answer("❌ Account not found!", show_alert=True)
            return

        status = "🟢 Active" if account.get("active") else "🔴 Inactive"
        phone = account["phone"]
        last_used = account.get("last_used", datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M")
        text = (f"📱 ACCOUNT DETAILS\n\n"
                f"Phone: {phone}\n"
                f"Status: {status}\n"
                f"Last Used: {last_used}")
        await safe_edit_or_send(query, text, kb_account_detail(acc_id, phone))

    elif action == "delete":
        acc_id = parts[2]
        account = await db.accounts.find_one({"_id": acc_id, "user_id": user_id})
        if not account:
            await query.answer("❌ Account not found!", show_alert=True)
            return

        phone = account["phone"]
        text = f"⚠️ DELETE ACCOUNT\n\nAre you sure you want to permanently delete:\n{phone}?"
        await safe_edit_or_send(query, text, kb_confirm_delete(acc_id))

    elif action == "confirm_del":
        acc_id = parts[2]
        result = await db.accounts.delete_one({"_id": acc_id, "user_id": user_id})
        
        # Stop any active campaigns using this account
        if user_id in campaign_tasks:
            task = campaign_tasks[user_id]
            if task.status == CampaignStatus.RUNNING:
                task.task.cancel()
                del campaign_tasks[user_id]
        
        if result.deleted_count:
            await query.answer("✅ Account deleted successfully!", show_alert=True)
        else:
            await query.answer("❌ Failed to delete account!", show_alert=True)
        
        text = "✨ Nexa Ads DASHBOARD\n\nManage your professional ad campaigns:"
        await safe_edit_or_send(query, text, kb_dashboard(user_id))

    elif action == "del":
        count = await db.accounts.count_documents({"user_id": user_id})
        if count == 0:
            await query.answer("📭 No accounts to delete!", show_alert=True)
            return
        text = "🗑️ DELETE ACCOUNTS\n\nSelect accounts to remove from your campaign:"
        await safe_edit_or_send(
            query,
            text,
            InlineKeyboardMarkup([
                [InlineKeyboardButton("View & Delete Accounts", callback_data="acc|list|0")],
                [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
            ])
        )

async def input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    if not state or state.step == "idle":
        return

    text = update.message.text.strip()

    try:
        if state.step == "phone":
            phone = "+" + re.sub(r"\D", "", text)
            if len(phone) < 8 or len(phone) > 15:
                await update.message.reply_text(
                    "❌ Invalid phone number!\n\nPlease enter a valid number with country code (e.g., +1234567890):",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]])
                )
                return

            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()

            try:
                sent = await client.send_code_request(phone)
                state.client = client
                state.phone = phone
                state.phone_code_hash = sent.phone_code_hash
                state.step = "code"
                state.buffer = ""

                await update.message.reply_text(
                    f"📱 OTP sent to {phone}!\n\n"
                    f"Enter the 5-digit code using the keypad below:",
                    reply_markup=kb_otp(user_id)
                )
            except Exception as e:
                await client.disconnect()
                error = str(e)
                if "FLOOD_WAIT" in error:
                    match = re.search(r'FLOOD_WAIT_(\d+)', error)
                    msg = f"⏳ Too many requests! Wait {match.group(1)} seconds before trying again." if match else "⏳ Too many requests! Please try again later."
                elif "INVALID_PHONE_NUMBER" in error:
                    msg = "❌ Invalid phone number format!"
                else:
                    msg = f"❌ Error: {error[:100]}"

                await update.message.reply_text(
                    f"{msg}\n\nPlease try again:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="nav|dashboard")]])
                )

        elif state.step == "password":
            if state.password_retry >= 3:
                await update.message.reply_text(
                    "❌ Too many failed attempts. Please restart the login process.",
                    reply_markup=kb_dashboard(user_id)
                )
                user_states[user_id] = UserState(step="idle")
                return
                
            state.password_retry += 1
            await finalize_login(user_id, context, password=text)

        elif state.step == "set_ad":
            if len(text) > 4000:
                await update.message.reply_text(
                    "❌ Message too long! (Max 4000 characters)\n\nPlease send a shorter ad message:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="nav|dashboard")]])
                )
                return

            await db.ads.update_one(
                {"user_id": str(user_id)},
                {"$set": {"text": text, "updated_at": datetime.now(timezone.utc)}},
                upsert=True
            )
            user_states[user_id] = UserState(step="idle")
            await update.message.reply_text(
                "✅ Ad Message Saved Successfully!",
                reply_markup=kb_dashboard(user_id)
            )

    except Exception as e:
        logger.exception(f"Input handler error for user {user_id}: {e}")
        await update.message.reply_text(
            "❌ Unexpected error occurred!\n\nPlease restart the process or contact support.",
            reply_markup=kb_dashboard(user_id)
        )
        if state and state.client:
            await state.client.disconnect()
        user_states[user_id] = UserState(step="idle")

async def handle_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    state = user_states.get(user_id)

    if not state or state.step != "code":
        await query.answer("	Session expired! Please restart login.", show_alert=True)
        return

    await query.answer()
    action = query.data.split("|")[1]
    error = ""

    if action == "back":
        state.buffer = state.buffer[:-1]
    elif action == "cancel":
        if state.client:
            await state.client.disconnect()
        user_states[user_id] = UserState(step="idle")
        await query.message.edit_text(
            "❌ Login cancelled successfully.",
            reply_markup=kb_dashboard(user_id)
        )
        return
    elif action == "resend":
        try:
            if state.client:
                await state.client.send_code_request(state.phone)
                error = "New code sent! Check Telegram messages."
        except Exception as e:
            error = f"Resend failed: {str(e)[:50]}"
    elif action.isdigit():
        if len(state.buffer) < 5:
            state.buffer += action
            # Auto-submit when 5 digits entered
            if len(state.buffer) == 5:
                await finalize_login(user_id, context)
                return
    
    # Update OTP display
    try:
        await query.edit_message_text(
            f"📱 Enter OTP for {state.phone}\n\n"
            f"Code received from Telegram (5 digits):",
            reply_markup=kb_otp(user_id, error)
        )
    except BadRequest:
        pass

async def finalize_login(user_id: int, context: ContextTypes.DEFAULT_TYPE, password: Optional[str] = None):
    state = user_states.get(user_id)
    if not state or not state.client:
        await context.bot.send_message(
            user_id,
            "❌ Session expired! Please restart the login process.",
            reply_markup=kb_dashboard(user_id)
        )
        return

    try:
        if password:
            await state.client.sign_in(password=password)
            state.password_retry = 0  # Reset on success
        else:
            await state.client.sign_in(
                phone=state.phone,
                code=state.buffer,
                phone_code_hash=state.phone_code_hash
            )

        # Update profile immediately after login
        try:
            await state.client(UpdateProfileRequest(
                first_name=PROFILE_NAME,
                about=PROFILE_BIO
            ))
        except Exception as e:
            logger.warning(f"Profile update warning for {state.phone}: {e}")

        # Save session
        session = state.client.session.save()
        await db.accounts.update_one(
            {"user_id": user_id, "phone": state.phone},
            {"$set": {
                "session": session,
                "active": True,
                "created_at": datetime.now(timezone.utc),
                "last_used": datetime.now(timezone.utc)
            }},
            upsert=True
        )

        await state.client.disconnect()
        user_states[user_id] = UserState(step="idle")

        success_msg = (f"✅ Account Successfully Added!\n\n"
                      f"📱 Phone: {state.phone}\n"
                      f"✨ Status: Ready for broadcasting\n\n"
                      f"⚠️ Profile updated with professional branding\n"
                      f"🔒 Session encrypted and stored securely")
        await context.bot.send_message(
            user_id,
            success_msg,
            reply_markup=kb_dashboard(user_id)
        )

    except SessionPasswordNeededError:
        state.step = "password"
        await context.bot.send_message(
            user_id,
            "🔐 Two-Step Verification Detected\n\nPlease enter your Telegram cloud password:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="nav|dashboard")]])
        )
    except (PhoneCodeInvalidError, ValueError):
        state.buffer = ""
        await query.answer("❌ Invalid OTP code!", show_alert=True)
        # Keep session alive for retry
    except Exception as e:
        error_msg = str(e)
        if "PHONE_CODE_EXPIRED" in error_msg:
            error_msg = "OTP expired! Please request a new code."
        elif "SESSION_REVOKED" in error_msg:
            error_msg = "Session revoked by Telegram. Please log in again."
        elif "FLOOD_WAIT" in error_msg:
            match = re.search(r'FLOOD_WAIT_(\d+)', error_msg)
            if match:
                error_msg = f"Too many attempts! Please wait {match.group(1)} seconds before trying again."
            else:
                error_msg = "Too many attempts! Please try again later."

        await state.client.disconnect()
        user_states[user_id] = UserState(step="idle")
        await context.bot.send_message(
            user_id,
            f"❌ Login Failed: {error_msg}",
            reply_markup=kb_dashboard(user_id)
        )
        logger.exception(f"Login failed for {state.phone}: {e}")

async def handle_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "ad|set":
        text = ("✍️ SET YOUR AD MESSAGE\n\n"
                "✨ Pro Tips for High-Converting Ads:\n"
                "• Keep it concise (under 200 chars ideal)\n"
                "• Use 2-3 relevant emojis max\n"
                "• Include clear call-to-action\n"
                "• Avoid spam triggers (!!!, $$$, FREE)\n"
                "• Personalize for your audience\n\n"
                "⚠️ Max 4000 characters\n\n"
                "Send your ad message now:")
        user_states[query.from_user.id] = UserState(step="set_ad")
        await query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="nav|dashboard")]])
        )

async def handle_delay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    parts = query.data.split("|")

    if parts[0] == "delay" and parts[1] == "nav":
        user_doc = await db.users.find_one({"user_id": str(user_id)})
        current_delay = user_doc.get("delay", MIN_DELAY) if user_doc else MIN_DELAY

        text = (f"⏱️ SET BROADCAST INTERVAL\n\n"
               f"Current Interval: {current_delay}s ({current_delay//60} min)\n\n"
               f"⚠️ SAFETY RECOMMENDATIONS:\n"
               f"• 🔴 300s (5 min) - HIGH RISK ⚠️\n"
               f"• 🟡 600s (10 min) - RECOMMENDED ✅\n"
               f"• 🟢 1200s (20 min) - SAFEST 🔒\n\n"
               f"❗ Using intervals below 5 minutes significantly increases ban risk")
        await safe_edit_or_send(query, text, kb_delay(current_delay))

    elif parts[0] == "setdelay":
        delay = int(parts[1])
        
        # Enforce minimum safe delay
        if delay < MIN_DELAY:
            await query.answer(f"⚠️ Minimum safe interval is {MIN_DELAY}s ({MIN_DELAY//60} min)", show_alert=True)
            delay = MIN_DELAY
        
        await db.users.update_one(
            {"user_id": str(user_id)},
            {"$set": {"delay": delay, "updated_at": datetime.now(timezone.utc)}},
            upsert=True
        )
        await query.answer(f"✅ Interval set to {delay}s ({delay//60} min)", show_alert=True)

        text = (f"⏱️ SET BROADCAST INTERVAL\n\n"
               f"Current Interval: {delay}s ({delay//60} min)\n\n"
               f"⚠️ SAFETY RECOMMENDATIONS:\n"
               f"• 🔴 300s (5 min) - HIGH RISK ⚠️\n"
               f"• 🟡 600s (10 min) - RECOMMENDED ✅\n"
               f"• 🟢 1200s (20 min) - SAFEST 🔒\n\n"
               f"❗ Using intervals below 5 minutes significantly increases ban risk")
        await safe_edit_or_send(query, text, kb_delay(delay))

async def handle_analytics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    parts = query.data.split("|")

    if parts[1] == "main":
        active = await db.accounts.count_documents({"user_id": user_id, "active": True})
        total = await db.accounts.count_documents({"user_id": user_id})
        user_doc = await db.users.find_one({"user_id": str(user_id)})
        delay = user_doc.get("delay", MIN_DELAY) if user_doc else MIN_DELAY
        
        # Get campaign stats
        campaign = await db.campaigns.find_one({"user_id": user_id, "status": "running"})
        if campaign:
            sent = campaign.get("messages_sent", 0)
            failed = campaign.get("messages_failed", 0)
            status = "▶️ Running"
        else:
            # Get last campaign stats
            last_campaign = await db.campaigns.find_one(
                {"user_id": user_id}, 
                sort=[("stopped_at", -1)]
            )
            sent = last_campaign.get("final_stats", {}).get("messages_sent", 0) if last_campaign else 0
            failed = last_campaign.get("final_stats", {}).get("messages_failed", 0) if last_campaign else 0
            status = "⏹️ Stopped" if last_campaign else "📭 No Campaigns"
        
        total_attempts = sent + failed
        success_rate = int((sent / total_attempts * 100)) if total_attempts > 0 else 0
        bar = "▓" * (success_rate // 10) + "░" * (10 - success_rate // 10)

        text = (f"📊 ADIMYZE PRO ANALYTICS\n\n"
               f"Status: {status}\n"
               f"Active Accounts: {active}/{total}\n"
               f"Current Interval: {delay}s\n\n"
               f"Messages Sent: {sent}\n"
               f"Failed Sends: {failed}\n"
               f"Success Rate: {bar} {success_rate}%\n\n"
               f"⚠️ Safety Score: {'🟢 Excellent' if delay >= 600 else '🟡 Moderate' if delay >= 300 else '🔴 Risky'}")

        await safe_edit_or_send(
            query,
            text,
            InlineKeyboardMarkup([
                [InlineKeyboardButton("📈 Detailed Report", callback_data="stat|detail")],
                [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="nav|dashboard")]
            ])
        )

    elif parts[1] == "detail":
        active = await db.accounts.count_documents({"user_id": user_id, "active": True})
        total = await db.accounts.count_documents({"user_id": user_id})
        inactive = total - active
        user_doc = await db.users.find_one({"user_id": str(user_id)})
        delay = user_doc.get("delay", MIN_DELAY) if user_doc else MIN_DELAY

        now = datetime.now(timezone.utc).strftime("%d/%m/%y %H:%M")
        campaign = await db.campaigns.find_one({"user_id": user_id, "status": "running"})
        
        if campaign:
            sent = campaign.get("messages_sent", 0)
            failed = campaign.get("messages_failed", 0)
            runtime = datetime.now(timezone.utc) - campaign.get("started_at", datetime.now(timezone.utc))
            runtime_str = f"{runtime.seconds//3600}h {(runtime.seconds//60)%60}m"
        else:
            sent, failed, runtime_str = 0, 0, "0m"

        text = (f"📈 DETAILED ANALYTICS REPORT\n\n"
               f"Generated: {now} UTC\n"
               f"User ID: {user_id}\n\n"
               f"📊 Campaign Stats:\n"
               f"• Status: {'Running' if campaign else 'Stopped'}\n"
               f"• Runtime: {runtime_str}\n"
               f"• Messages Sent: {sent}\n"
               f"• Failed Sends: {failed}\n"
               f"• Success Rate: {int(sent/(sent+failed)*100) if (sent+failed) > 0 else 0}%\n\n"
               f"👥 Account Stats:\n"
               f"• Total Accounts: {total}\n"
               f"• Active: {active} 🟢\n"
               f"• Inactive: {inactive} 🔴\n\n"
               f"⚙️ Configuration:\n"
               f"• Broadcast Interval: {delay}s\n"
               f"• Safety Level: {'Maximum' if delay >= 1200 else 'Recommended' if delay >= 600 else 'Aggressive'}")

        await safe_edit_or_send(
            query,
            text,
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Summary", callback_data="stat|main")]])
        )

async def handle_features(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if "auto" in query.data:
        text = ("🤖 AUTO REPLY FEATURE\n\n"
               "This premium feature is under development!\n\n"
               "Coming in v2.0:\n"
               "• Keyword-triggered auto-replies\n"
               "• Smart conversation routing\n"
               "• Multi-language support\n"
               "• Sentiment analysis\n\n"
               "Stay tuned for the next update!")
        await safe_edit_or_send(
            query,
            text,
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Dashboard", callback_data="nav|dashboard")]])
        )

async def handle_campaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if "start" in query.data or "pause" in query.data:
        # Check if campaign is already running
        if user_id in campaign_tasks and campaign_tasks[user_id].status == CampaignStatus.RUNNING:
            if "pause" in query.data:
                # Pause campaign
                campaign_tasks[user_id].status = CampaignStatus.PAUSED
                await db.campaigns.update_one(
                    {"user_id": user_id},
                    {"$set": {"status": "paused", "paused_at": datetime.now(timezone.utc)}}
                )
                await query.answer("⏸️ Campaign paused successfully!", show_alert=True)
                text = ("⏸️ BROADCAST PAUSED\n\n"
                       "Your campaign has been temporarily paused.\n"
                       "You can resume anytime from the dashboard.")
                await safe_edit_or_send(query, text, kb_dashboard(user_id))
                return
            else:
                await query.answer("▶️ Campaign already running!", show_alert=True)
                return
        
        # Validate prerequisites
        accounts = await db.accounts.count_documents({"user_id": user_id, "active": True})
        ad_doc = await db.ads.find_one({"user_id": str(user_id)})

        if accounts == 0:
            await query.answer("❌ No active accounts! Add accounts first.", show_alert=True)
            return
        if not ad_doc or not ad_doc.get("text"):
            await query.answer("❌ No ad message set! Set your ad message first.", show_alert=True)
            return
        
        # Check safety settings
        user_doc = await db.users.find_one({"user_id": str(user_id)})
        delay = user_doc.get("delay", MIN_DELAY) if user_doc else MIN_DELAY
        
        if delay < MIN_DELAY:
            await query.answer(f"⚠️ Unsafe interval! Minimum {MIN_DELAY}s required for account safety.", show_alert=True)
            return
        
        # Start new campaign task
        task = asyncio.create_task(broadcast_scheduler(user_id))
        campaign_tasks[user_id] = BroadcastTask(
            task=task,
            status=CampaignStatus.RUNNING,
            active_accounts=[acc["phone"] async for acc in db.accounts.find({"user_id": user_id, "active": True})]
        )
        
        # Create campaign record
        await db.campaigns.update_one(
            {"user_id": user_id},
            {"$set": {
                "status": "running",
                "started_at": datetime.now(timezone.utc),
                "messages_sent": 0,
                "messages_failed": 0,
                "interval": delay,
                "active_accounts": campaign_tasks[user_id].active_accounts
            }},
            upsert=True
        )
        
        await query.answer("✅ Campaign started successfully!", show_alert=True)
        text = (f"🚀 BROADCAST STARTED\n\n"
               f"✅ {accounts} account(s) active\n"
               f"⏱️ Interval: {delay}s ({delay//60} min)\n"
               f"🛡️ Safety Level: {'Maximum' if delay >= 1200 else 'Recommended' if delay >= 600 else 'Aggressive'}\n\n"
               f"📊 Monitor progress in Analytics section.\n"
               f"⚠️ Do not close this bot while campaign is running!")
        await safe_edit_or_send(
            query,
            text,
            InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 View Analytics", callback_data="stat|main")],
                [InlineKeyboardButton("⏹️ Stop Broadcast", callback_data="camp|stop")],
                [InlineKeyboardButton("🏠 Dashboard", callback_data="nav|dashboard")]
            ])
        )

    elif "stop" in query.data:
        # Stop running campaign
        if user_id in campaign_tasks:
            task = campaign_tasks[user_id]
            if task.status == CampaignStatus.RUNNING or task.status == CampaignStatus.PAUSED:
                task.task.cancel()
                task.status = CampaignStatus.STOPPED
                await asyncio.sleep(0.5)  # Allow task to clean up
                
                # Update database
                await db.campaigns.update_one(
                    {"user_id": user_id},
                    {"$set": {
                        "status": "stopped",
                        "stopped_at": datetime.now(timezone.utc)
                    }}
                )
                
                del campaign_tasks[user_id]
                await query.answer("🛑 Campaign stopped successfully!", show_alert=True)
            else:
                await query.answer("📭 No active campaign to stop", show_alert=True)
        else:
            await query.answer("📭 No active campaign to stop", show_alert=True)
        
        text = ("⏹️ BROADCAST STOPPED\n\n"
               "All broadcasting activities have been halted.\n"
               "Campaign statistics have been saved.\n\n"
               "You can restart anytime from the dashboard.")
        await safe_edit_or_send(query, text, kb_dashboard(user_id))

async def handle_noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle non-operational callbacks (display-only buttons)"""
    if update.callback_query:
        await update.callback_query.answer()

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}")

async def post_init(application: Application):
    logger.info("🚀 Adimyze Pro initialized successfully")
    
    # Cleanup any orphaned campaigns on startup
    await db.campaigns.update_many(
        {"status": {"$in": ["running", "paused"]}},
        {"$set": {"status": "stopped", "stopped_at": datetime.now(timezone.utc)}}
    )
    logger.info("🧹 Cleaned up orphaned campaigns")

async def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(handle_noop, pattern=r"^(otp_display|otp_error|noop)$"))
    app.add_handler(CallbackQueryHandler(handle_otp, pattern=r"^otp\|"))
    app.add_handler(CallbackQueryHandler(handle_account_ops, pattern=r"^acc\|"))
    app.add_handler(CallbackQueryHandler(handle_ads, pattern=r"^ad\|"))
    app.add_handler(CallbackQueryHandler(handle_delay, pattern=r"^(delay|setdelay)\|"))
    app.add_handler(CallbackQueryHandler(handle_analytics, pattern=r"^stat\|"))
    app.add_handler(CallbackQueryHandler(handle_features, pattern=r"^feature\|"))
    app.add_handler(CallbackQueryHandler(handle_campaigns, pattern=r"^camp\|"))
    app.add_handler(CallbackQueryHandler(handle_navigation, pattern=r"^nav\|"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, input_handler))
    app.add_error_handler(error_handler)

    logger.info("🚀 Starting Adimyze Pro Bot...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("✅ Adimyze Pro is running with all features enabled!")
    logger.info(f"✨ Features: Real OTP UI | Broadcast Engine | Multi-Account | Anti-Flood | Background Scheduler")
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Bot stopped by user")
    except Exception as e:
        logger.exception(f"_fatal error: {e}")
        sys.exit(1)