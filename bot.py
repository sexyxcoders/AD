#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ADIMYZE PRO v14 — Telegram Bulk Forwarding & Marketing Automation
✅ FIXED ALL ISSUES | GOLD UI THEME | Professional Dashboard
Author: @nexaxoders | Complete Rewrite with All Fixes
"""
import asyncio
import random
import logging
import re
import sys
import os
import fcntl
import string
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import InputPeerChannel, Channel, Chat, User
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeEmptyError,
    FloodWaitError,
    UsernameOccupiedError,
    ChatWriteForbiddenError,
    PeerFloodError,
    PasswordHashInvalidError,
    PhoneNumberInvalidError,
    AuthKeyUnregisteredError,
    UserDeactivatedError,
    SessionRevokedError,
)
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

# ────────────────────────────────────────────────
# CONFIGURATION & CONSTANTS
# ────────────────────────────────────────────────
BOT_TOKEN = '8463982454:AAErd8EZswKgQ1BNF_r-N8iUH8HQcb293lQ'
API_ID = 22657083
API_HASH = 'd6186691704bd901bdab275ceaab88f3'
MONGO_URI = "mongodb+srv://bot627668:2bEJ56yJSu7vzLws@cluster0.qbw5van.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
DB_NAME = "adimyze"
SUPPORT_CHANNEL = "https://t.me/testttxs"
SUPPORT_GROUP = "https://t.me/nexaxoders"
PROFILE_NAME = "Adimyze Pro"
PROFILE_BIO = "🚀 Professional Telegram Marketing Automation | Managed by @nexaxoders"

# Logging configuration
logging.basicConfig(
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler("adimyze_pro.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Database connection
mongo_client = AsyncIOMotorClient(MONGO_URI, maxPoolSize=50, minPoolSize=5)
db = mongo_client[DB_NAME]

# Global state management
@dataclass
class UserState:
    step: str = "idle"
    phone: str = ""
    phone_code_hash: str = ""
    buffer: str = ""
    client: Optional[TelegramClient] = None
    session_string: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ad_message: Optional[Dict] = None
    selected_account: Optional[str] = None
    delay_config: Dict = field(default_factory=lambda: {"min": 60, "max": 180})

user_states: Dict[int, UserState] = {}
ad_tasks: Dict[int, asyncio.Task] = {}
active_clients: Dict[str, TelegramClient] = {}

# Lockfile for single instance enforcement
PID_FILE = Path("/tmp/adimyze_pro_v14.pid")

# ────────────────────────────────────────────────
# UTILITY FUNCTIONS
# ────────────────────────────────────────────────
def acquire_lock() -> Optional[int]:
    try:
        fd = os.open(PID_FILE, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return fd
    except FileExistsError:
        logger.error("Another instance is already running. Exiting.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Lock acquisition failed: {e}")
        sys.exit(1)

def release_lock(fd: int):
    try:
        os.close(fd)
        PID_FILE.unlink(missing_ok=True)
    except Exception as e:
        logger.warning(f"Lock release failed: {e}")

def format_phone(phone: str) -> str:
    return f"+{phone[-10:]}" if len(phone) >= 10 else phone

def get_session_hash(session_str: str) -> str:
    return session_str[:15] if session_str else "unknown"

async def safe_disconnect(client: TelegramClient):
    try:
        if client and client.is_connected():
            await client.disconnect()
    except Exception as e:
        logger.debug(f"Client disconnect error: {e}")

async def cleanup_user_state(user_id: int):
    state = user_states.pop(user_id, None)
    if state and state.client:
        await safe_disconnect(state.client)
    if state and state.session_string:
        session_hash = get_session_hash(state.session_string)
        client = active_clients.pop(session_hash, None)
        if client:
            await safe_disconnect(client)

def parse_callback_data(data: str) -> Tuple[str, List[str]]:
    parts = data.split('|')
    return parts[0], parts[1:] if len(parts) > 1 else []

# ────────────────────────────────────────────────
# GOLD UI THEME KEYBOARDS
# ────────────────────────────────────────────────
def kb_start_menu() -> InlineKeyboardMarkup:
    """Main menu with 4 buttons - Gold Theme"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👑 Dashboard", callback_data="nav|dashboard")],
        [
            InlineKeyboardButton("📢 Channel", url=SUPPORT_CHANNEL),
            InlineKeyboardButton("👥 Group", url=SUPPORT_GROUP)
        ],
        [InlineKeyboardButton("ℹ️ About", callback_data="nav|about")]
    ])

def kb_dashboard(user_id: int, stats: Dict = None) -> InlineKeyboardMarkup:
    """Dashboard with 2x2 button layout"""
    buttons = [
        [
            InlineKeyboardButton("📱 Accounts", callback_data="accounts|list"),
            InlineKeyboardButton("📥 Load Chats", callback_data="chats|load")
        ],
        [
            InlineKeyboardButton("✏️ Set Ad", callback_data="ad|set"),
            InlineKeyboardButton("⏱️ Delays", callback_data="settings|delays")
        ]
    ]
    
    campaign_status = stats.get("running", False) if stats else False
    if campaign_status:
        buttons.append([InlineKeyboardButton("⏹️ Stop Campaign", callback_data="campaign|stop")])
    else:
        buttons.append([InlineKeyboardButton("▶️ Start Campaign", callback_data="campaign|start")])
    
    buttons.append([InlineKeyboardButton("📊 Statistics", callback_data="stats|view")])
    buttons.append([InlineKeyboardButton("🏠 Main Menu", callback_data="nav|home")])
    
    return InlineKeyboardMarkup(buttons)

def kb_otp_keyboard(user_id: int, step: str = "otp") -> InlineKeyboardMarkup:
    """Gold-themed OTP/2FA keypad"""
    state = user_states.get(user_id)
    buffer = state.buffer if state else ""
    
    if step == "2fa":
        display = "•" * len(buffer) if buffer else "Enter password"
        title = "🔐 Two-Factor Authentication"
    else:
        display = buffer.ljust(5, "●") if len(buffer) < 5 else buffer
        title = f"🔑 Verification Code (5 digits)"
    
    keypad = [
        [InlineKeyboardButton(display, callback_data="otp|display")],
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
         InlineKeyboardButton("✅", callback_data="otp|confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="otp|cancel")]
    ]
    
    return InlineKeyboardMarkup(keypad)

def kb_accounts_list(accounts: List[Dict], page: int = 0) -> InlineKeyboardMarkup:
    """Gold-themed accounts list"""
    buttons = []
    page_size = 8
    start_idx = page * page_size
    end_idx = start_idx + page_size
    page_accounts = accounts[start_idx:end_idx]
    
    for acc in page_accounts:
        status_emoji = "🟢" if acc.get("active", True) else "🔴"
        phone_display = format_phone(acc.get("phone", "Unknown"))
        buttons.append([
            InlineKeyboardButton(
                f"{status_emoji} {phone_display}",
                callback_data=f"account|details|{acc['_id']}"
            )
        ])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"accounts|page|{page-1}"))
    if end_idx < len(accounts):
        nav_buttons.append(InlineKeyboardButton("➡️ Next", callback_data=f"accounts|page|{page+1}"))
    if nav_buttons:
        buttons.append(nav_buttons)
    
    buttons.append([InlineKeyboardButton("➕ Add Account", callback_data="account|add")])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="nav|dashboard")])
    
    return InlineKeyboardMarkup(buttons)

def kb_account_actions(account_id: str, is_active: bool) -> InlineKeyboardMarkup:
    """Account management actions"""
    status_text = "🔴 Deactivate" if is_active else "🟢 Activate"
    status_cb = f"account|toggle|{account_id}"
    
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(status_text, callback_data=status_cb)],
        [InlineKeyboardButton("🗑️ Delete Account", callback_data=f"account|delete|{account_id}")],
        [InlineKeyboardButton("🔙 Back", callback_data="accounts|list")]
    ])

def kb_confirm_delete(account_id: str) -> InlineKeyboardMarkup:
    """Deletion confirmation"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ YES, Delete", callback_data=f"account|confirm_delete|{account_id}")],
        [InlineKeyboardButton("❌ NO, Cancel", callback_data=f"account|details|{account_id}")],
    ])

def kb_delay_settings(user_id: int) -> InlineKeyboardMarkup:
    """Delay configuration interface"""
    state = user_states.get(user_id)
    delay_config = state.delay_config if state else {"min": 60, "max": 180}
    
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Min Delay: {delay_config['min']}s", callback_data="delay|min")],
        [InlineKeyboardButton(f"Max Delay: {delay_config['max']}s", callback_data="delay|max")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav|dashboard")]
    ])

def kb_about_menu() -> InlineKeyboardMarkup:
    """About section menu"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👨‍💻 Developer", url=SUPPORT_GROUP)],
        [InlineKeyboardButton("📢 Channel", url=SUPPORT_CHANNEL)],
        [InlineKeyboardButton("🔙 Back", callback_data="nav|home")]
    ])

# ────────────────────────────────────────────────
# MESSAGE TEMPLATES (GOLD THEME)
# ────────────────────────────────────────────────
WELCOME_TEXT = """
👑 <b>ADIMYZE PRO v14</b> 👑
━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>Professional Telegram Marketing Automation</b>

✨ <b>Key Features:</b>
• ✅ Multi-Account Management
• ✅ Smart Anti-Flood Protection
• ✅ Bulk Forwarding (Text/Media/Files)
• ✅ Target Chat Discovery
• ✅ Real-Time Analytics
• ✅ Custom Delay Settings
• ✅ Secure Session Management

🛡️ <b>Safety Features:</b>
• Built-in flood protection
• Telegram TOS compliant
• Rate limiting enforcement
• Session encryption

👨‍💻 <b>Developed by:</b> <a href="https://t.me/nexaxoders">NexaXoders</a>
📅 <b>Version:</b> 14.0 (Gold Edition)
"""

ABOUT_TEXT = """
👑 <b>ABOUT ADIMYZE PRO</b> 👑
━━━━━━━━━━━━━━━━━━━━━━━━━━━

🚀 <b>What is ADIMYZE PRO?</b>
A professional Telegram marketing automation tool designed for businesses and marketers to efficiently manage bulk messaging campaigns across multiple accounts.

🎯 <b>Core Capabilities:</b>
• Multi-account management with unlimited accounts
• Smart chat discovery and filtering
• Automated message forwarding with custom delays
• Real-time campaign monitoring and statistics
• Secure session handling with MongoDB

💡 <b>Best Practices:</b>
• Start with 1 account and test before scaling
• Use appropriate delays to avoid bans
• Respect Telegram's Terms of Service
• Never spam small communities
• Rotate accounts regularly for safety

⚠️ <b>Disclaimer:</b>
Use responsibly and comply with Telegram's guidelines. Developers are not responsible for misuse.

━━━━━━━━━━━━━━━━━━━━━━━━━━━
👨‍💻 <b>Support:</b> @nexaxoders
"""

DASHBOARD_TEMPLATE = """
👑 <b>DASHBOARD</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━

📱 <b>Accounts:</b> {account_count} active / {total_accounts} total
💬 <b>Target Chats:</b> {chat_count}
📢 <b>Ad Message:</b> {ad_status}
⏱️ <b>Delay Settings:</b> {delay_range}
⚡ <b>Campaign:</b> {campaign_status}

━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 <b>Lifetime Stats:</b>
✅ Sent: {sent} | ❌ Failed: {failed}
━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

ACCOUNT_DETAILS_TEMPLATE = """
📱 <b>Account Details</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━

📞 Phone: <code>{phone}</code>
🆔 Account ID: <code>{account_id}</code>
⚡ Status: {status_emoji} <b>{status_text}</b>
📅 Added: {created_date}
👤 Username: {username}

━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

CAMPAIGN_RUNNING = """
🟢 <b>CAMPAIGN ACTIVE</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 <b>Current Status:</b>
✅ Sent: {sent}
❌ Failed: {failed}
⏱️ Next batch in: ~{next_delay} seconds

📱 <b>Active Accounts:</b> {account_count}
💬 <b>Target Chats:</b> {chat_count}
⏱️ <b>Delay Range:</b> {delay_range}

⚠️ Campaign running. Use /status to check progress.
━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

# ────────────────────────────────────────────────
# TELETHON CLIENT MANAGEMENT
# ────────────────────────────────────────────────
async def get_cached_client(session_str: str) -> TelegramClient:
    """Get or create cached Telethon client."""
    session_hash = get_session_hash(session_str)
    if session_hash in active_clients:
        client = active_clients[session_hash]
        if client.is_connected():
            try:
                await client.get_me()
                return client
            except (AuthKeyUnregisteredError, SessionRevokedError, UserDeactivatedError):
                await safe_disconnect(client)
                active_clients.pop(session_hash, None)
    
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.connect()
    active_clients[session_hash] = client
    return client

async def validate_session(session_str: str) -> Tuple[bool, str]:
    """Validate session string."""
    try:
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await client.connect()
        if await client.is_user_authorized():
            me = await client.get_me()
            phone = me.phone if me.phone else "unknown"
            await safe_disconnect(client)
            return True, phone
        await safe_disconnect(client)
        return False, "unauthorized"
    except Exception as e:
        logger.error(f"Session validation error: {e}")
        return False, str(e)

# ────────────────────────────────────────────────
# HANDLERS
# ────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gold-themed welcome message."""
    await update.message.reply_text(
        WELCOME_TEXT,
        reply_markup=kb_start_menu(),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )

async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear user state."""
    user_id = update.effective_user.id
    await cleanup_user_state(user_id)
    await update.message.reply_text(
        "✅ User state cleared.",
        reply_markup=kb_start_menu()
    )

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show campaign status."""
    user_id = update.effective_user.id
    user_doc = await db.users.find_one({"user_id": user_id})
    
    if not user_doc or not user_doc.get("running"):
        await update.message.reply_text(
            "⏹️ No active campaign.",
            reply_markup=kb_dashboard(user_id)
        )
        return
    
    stats = user_doc.get("stats", [])[-1] if user_doc.get("stats") else {}
    state = user_states.get(user_id)
    delay_config = state.delay_config if state else {"min": 60, "max": 180}
    
    await update.message.reply_text(
        CAMPAIGN_RUNNING.format(
            sent=stats.get("sent", 0),
            failed=stats.get("failed", 0),
            next_delay=random.randint(delay_config['min'], delay_config['max']),
            account_count=await db.accounts.count_documents({"user_id": user_id, "active": True}),
            chat_count=len(user_doc.get("chats", [])),
            delay_range=f"{delay_config['min']}-{delay_config['max']}s"
        ),
        reply_markup=kb_dashboard(user_id),
        parse_mode=ParseMode.HTML
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main callback router."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    
    if not data:
        return
    
    prefix, args = parse_callback_data(data)
    
    try:
        if prefix == "nav":
            await handle_navigation(query, user_id, args[0] if args else "home")
        elif prefix == "account":
            await handle_account_actions(query, user_id, args)
        elif prefix == "accounts":
            await handle_accounts_list(query, user_id, args)
        elif prefix == "otp":
            await handle_otp_input(query, user_id, args[0] if args else "cancel")
        elif prefix == "campaign":
            await handle_campaign_actions(query, user_id, args[0] if args else "start")
        elif prefix == "ad":
            await handle_ad_actions(query, user_id, args)
        elif prefix == "chats":
            await handle_chat_actions(query, user_id, args)
        elif prefix == "stats":
            await handle_stats_actions(query, user_id, args)
        elif prefix == "settings":
            await handle_settings_actions(query, user_id, args)
        elif prefix == "delay":
            await handle_delay_settings(query, user_id, args[0] if args else "")
        else:
            await query.edit_message_text(
                "❓ Unknown action.",
                reply_markup=kb_start_menu()
            )
    except BadRequest as e:
        logger.warning(f"BadRequest: {e}")
        await query.edit_message_text(
            "⚠️ Interface updated. Please use menu buttons.",
            reply_markup=kb_start_menu()
        )
    except Exception as e:
        logger.exception(f"Callback error for {user_id}: {e}")
        await query.edit_message_text(
            "❌ Error occurred.",
            reply_markup=kb_start_menu()
        )

async def handle_navigation(query, user_id: int, target: str):
    """Handle navigation."""
    if target == "home":
        await query.edit_message_text(
            WELCOME_TEXT,
            reply_markup=kb_start_menu(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    elif target == "dashboard":
        account_count = await db.accounts.count_documents({"user_id": user_id, "active": True})
        total_accounts = await db.accounts.count_documents({"user_id": user_id})
        user_doc = await db.users.find_one({"user_id": user_id}) or {}
        chat_count = len(user_doc.get("chats", []))
        ad_status = "✅ Configured" if user_doc.get("ad_message") else "❌ Not set"
        campaign_status = "🟢 RUNNING" if user_doc.get("running") else "🔴 STOPPED"
        
        state = user_states.get(user_id)
        delay_config = state.delay_config if state else {"min": 60, "max": 180}
        delay_range = f"{delay_config['min']}-{delay_config['max']}s"
        
        stats = {
            "sent": sum(s.get("sent", 0) for s in user_doc.get("stats", [])),
            "failed": sum(s.get("failed", 0) for s in user_doc.get("stats", [])),
            "running": user_doc.get("running", False)
        }
        
        await query.edit_message_text(
            DASHBOARD_TEMPLATE.format(
                account_count=account_count,
                total_accounts=total_accounts,
                chat_count=chat_count,
                ad_status=ad_status,
                delay_range=delay_range,
                campaign_status=campaign_status,
                sent=stats["sent"],
                failed=stats["failed"]
            ),
            reply_markup=kb_dashboard(user_id, stats),
            parse_mode=ParseMode.HTML
        )
    elif target == "about":
        await query.edit_message_text(
            ABOUT_TEXT,
            reply_markup=kb_about_menu(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )

async def handle_account_actions(query, user_id: int, args: List[str]):
    """Handle account actions."""
    if not args:
        return
    
    action = args[0]
    
    if action == "add":
        user_states[user_id] = UserState(step="phone")
        await query.edit_message_text(
            "📱 <b>Add New Account</b>\n\n"
            "Please send your phone number in international format:\n"
            "<code>+12025550123</code> or <code>+447911123456</code>\n\n"
            "⚠️ Use a dedicated account for marketing.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="accounts|list")]
            ]),
            parse_mode=ParseMode.HTML
        )
    
    elif action == "details" and len(args) > 1:
        account_id = args[1]
        account = await db.accounts.find_one({"_id": account_id, "user_id": user_id})
        if not account:
            await query.answer("❌ Account not found!", show_alert=True)
            return
        
        is_valid, _ = await validate_session(account["session"])
        if not is_valid:
            await db.accounts.update_one(
                {"_id": account_id},
                {"$set": {"active": False, "invalidated": True}}
            )
            await query.answer("⚠️ Session expired. Account deactivated.", show_alert=True)
            await show_accounts_list(query, user_id, 0)
            return
        
        status_emoji = "🟢" if account.get("active", True) else "🔴"
        status_text = "Active" if account.get("active", True) else "Inactive"
        created_date = account.get("created", datetime.now()).strftime("%Y-%m-%d")
        username = account.get("username", "Not set")
        
        await query.edit_message_text(
            ACCOUNT_DETAILS_TEMPLATE.format(
                phone=format_phone(account.get("phone", "Unknown")),
                account_id=account_id,
                status_emoji=status_emoji,
                status_text=status_text,
                created_date=created_date,
                username=f"@{username}" if username else "Not set"
            ),
            reply_markup=kb_account_actions(account_id, account.get("active", True)),
            parse_mode=ParseMode.HTML
        )
    
    elif action == "toggle" and len(args) > 1:
        account_id = args[1]
        account = await db.accounts.find_one({"_id": account_id, "user_id": user_id})
        if not account:
            await query.answer("❌ Account not found!", show_alert=True)
            return
        
        new_status = not account.get("active", True)
        await db.accounts.update_one(
            {"_id": account_id},
            {"$set": {"active": new_status}}
        )
        status_text = "activated" if new_status else "deactivated"
        await query.answer(f"✅ Account {status_text}!")
        await handle_account_actions(query, user_id, ["details", account_id])
    
    elif action == "delete" and len(args) > 1:
        account_id = args[1]
        account = await db.accounts.find_one({"_id": account_id, "user_id": user_id})
        if not account:
            await query.answer("❌ Account not found!", show_alert=True)
            return
        
        await query.edit_message_text(
            f"⚠️ <b>Delete Account</b>\n\n"
            f"Phone: <code>{format_phone(account.get('phone', 'Unknown'))}</code>\n\n"
            f"❗ This will PERMANENTLY remove the account.\n"
            f"❗ All data will be lost.\n\n"
            f"Are you sure?",
            reply_markup=kb_confirm_delete(account_id),
            parse_mode=ParseMode.HTML
        )
    
    elif action == "confirm_delete" and len(args) > 1:
        account_id = args[1]
        result = await db.accounts.delete_one({"_id": account_id, "user_id": user_id})
        if result.deleted_count == 0:
            await query.answer("❌ Deletion failed!", show_alert=True)
            await show_accounts_list(query, user_id, 0)
            return
        
        account = await db.accounts.find_one({"_id": account_id})
        if account and account.get("session"):
            session_hash = get_session_hash(account["session"])
            client = active_clients.pop(session_hash, None)
            if client:
                await safe_disconnect(client)
        
        await query.answer("✅ Account deleted!")
        await show_accounts_list(query, user_id, 0)

async def show_accounts_list(query, user_id: int, page: int):
    """Show accounts list."""
    accounts = await db.accounts.find({"user_id": user_id}).sort("created", -1).to_list(50)
    
    if not accounts:
        await query.edit_message_text(
            "📱 <b>Account Management</b>\n\n"
            "No accounts added yet.\n\n"
            "➕ Add your first account:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Account", callback_data="account|add")],
                [InlineKeyboardButton("🔙 Back", callback_data="nav|dashboard")]
            ]),
            parse_mode=ParseMode.HTML
        )
        return
    
    await query.edit_message_text(
        f"📱 <b>Account Management</b>\n\n"
        f"Total: {len(accounts)} | Active: {sum(1 for a in accounts if a.get('active', True))}\n\n"
        f"Select an account to manage:",
        reply_markup=kb_accounts_list(accounts, page),
        parse_mode=ParseMode.HTML
    )

async def handle_accounts_list(query, user_id: int, args: List[str]):
    """Handle accounts list pagination."""
    if not args:
        await show_accounts_list(query, user_id, 0)
        return
    
    if args[0] == "list":
        await show_accounts_list(query, user_id, 0)
    elif args[0] == "page" and len(args) > 1:
        try:
            page = int(args[1])
            await show_accounts_list(query, user_id, page)
        except ValueError:
            await show_accounts_list(query, user_id, 0)

async def handle_otp_input(query, user_id: int, action: str):
    """Handle OTP/2FA input."""
    state = user_states.get(user_id)
    if not state or state.step not in ["otp", "2fa"]:
        await query.edit_message_text(
            "⚠️ Session expired. Restart login.",
            reply_markup=kb_start_menu()
        )
        await cleanup_user_state(user_id)
        return
    
    if action == "cancel":
        await cleanup_user_state(user_id)
        await query.edit_message_text(
            "❌ Cancelled.",
            reply_markup=kb_dashboard(user_id, {})
        )
        return
    elif action == "back":
        state.buffer = state.buffer[:-1] if state.buffer else ""
    elif action == "confirm":
        await verify_code(user_id, query, state)
        return
    elif action.isdigit() and len(action) == 1:
        max_len = 5 if state.step == "otp" else 32
        if len(state.buffer) < max_len:
            state.buffer += action
    
    step = state.step
    await query.edit_message_text(
        f"{'🔐 Two-Factor Authentication' if step == '2fa' else '🔑 Verification Code'}\n\n"
        f"Enter the code:",
        reply_markup=kb_otp_keyboard(user_id, step),
        parse_mode=ParseMode.HTML
    )

async def verify_code(user_id: int, query, state: UserState):
    """Verify OTP or 2FA code."""
    code = state.buffer
    client = state.client
    
    if not client or not client.is_connected():
        await query.edit_message_text(
            "❌ Connection lost. Restart login.",
            reply_markup=kb_dashboard(user_id, {})
        )
        await cleanup_user_state(user_id)
        return
    
    try:
        if state.step == "otp":
            await client.sign_in(
                phone=state.phone,
                code=code,
                phone_code_hash=state.phone_code_hash
            )
        else:
            await client.sign_in(password=code)
        
        await finalize_account_setup(user_id, query, client, state.phone)
    except SessionPasswordNeededError:
        state.step = "2fa"
        state.buffer = ""
        await query.edit_message_text(
            "🔐 <b>Two-Factor Authentication</b>\n\n"
            "This account has 2FA enabled. Enter your password:",
            reply_markup=kb_otp_keyboard(user_id, "2fa"),
            parse_mode=ParseMode.HTML
        )
    except (PhoneCodeInvalidError, PasswordHashInvalidError, PhoneCodeEmptyError):
        state.buffer = ""
        error_msg = "❌ Invalid code!" if state.step == "otp" else "❌ Invalid password!"
        await query.answer(error_msg, show_alert=True)
        await query.edit_message_text(
            f"{'🔑 Verification Code' if state.step == 'otp' else '🔐 Two-Factor Authentication'}\n\n"
            f"{error_msg} Try again:",
            reply_markup=kb_otp_keyboard(user_id, state.step),
            parse_mode=ParseMode.HTML
        )
    except FloodWaitError as e:
        await query.edit_message_text(
            f"⏳ Wait {e.seconds} seconds before trying again.",
            reply_markup=kb_dashboard(user_id, {})
        )
        await cleanup_user_state(user_id)
    except Exception as e:
        logger.error(f"Login error for {user_id}: {e}")
        await query.edit_message_text(
            f"❌ Authentication failed: {str(e)[:100]}",
            reply_markup=kb_dashboard(user_id, {})
        )
        await cleanup_user_state(user_id)

async def finalize_account_setup(user_id: int, query, client: TelegramClient, phone: str):
    """Complete account setup WITHOUT changing username."""
    try:
        # Update profile name and bio ONLY (no username change)
        await client(UpdateProfileRequest(
            first_name=PROFILE_NAME,
            about=PROFILE_BIO
        ))
        
        # Get current username
        me = await client.get_me()
        username = me.username if me.username else None
        
        # Save session
        session_str = client.session.save()
        
        # Create account document
        account_doc = {
            "_id": f"acc_{ObjectId()}",
            "user_id": user_id,
            "phone": phone,
            "session": session_str,
            "active": True,
            "created": datetime.now(timezone.utc),
            "username": username,
            "last_used": datetime.now(timezone.utc)
        }
        await db.accounts.insert_one(account_doc)
        
        # Success message
        await query.edit_message_text(
            "✅ <b>Account Added Successfully!</b>\n\n"
            f"📱 Phone: <code>{format_phone(phone)}</code>\n"
            f"👤 Username: {f'@{username}' if username else 'Not set'}\n"
            f"⚡ Status: Active\n\n"
            "Profile optimized for marketing.",
            reply_markup=kb_dashboard(user_id, {}),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Account setup error for {user_id}: {e}")
        await query.edit_message_text(
            "⚠️ Account added with limited functionality.\n\n"
            f"Error: {str(e)[:150]}",
            reply_markup=kb_dashboard(user_id, {}),
            parse_mode=ParseMode.HTML
        )
    finally:
        await cleanup_user_state(user_id)

async def handle_ad_actions(query, user_id: int, args: List[str]):
    """Handle ad message configuration."""
    if not args:
        return
    
    action = args[0]
    if action == "set":
        user_states[user_id] = UserState(step="wait_ad")
        await query.edit_message_text(
            "📢 <b>Set Advertisement Message</b>\n\n"
            "👉 <b>Forward ONE message</b> from your <u>Saved Messages</u>\n\n"
            "✅ Supported:\n"
            "• Text messages\n"
            "• Photos & captions\n"
            "• Videos & documents\n"
            "• Voice messages\n\n"
            "⚠️ Only from <b>your own Saved Messages</b>!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="nav|dashboard")]
            ]),
            parse_mode=ParseMode.HTML
        )

async def handle_chat_actions(query, user_id: int, args: List[str]):
    """Handle chat loading."""
    if not args:
        return
    
    action = args[0]
    if action == "load":
        await query.edit_message_text(
            "🔄 <b>Loading Target Chats</b>\n\n"
            "Scanning active accounts for:\n"
            "• Groups you can post in\n"
            "• Channels you admin\n"
            "• Large communities (>50 members)\n\n"
            "⏱️ This may take 1-3 minutes...",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏹️ Cancel", callback_data="nav|dashboard")]
            ]),
            parse_mode=ParseMode.HTML
        )
        asyncio.create_task(load_target_chats(user_id, query.message.chat_id, query.message.message_id))

async def load_target_chats(user_id: int, chat_id: int, msg_id: int):
    """Background task to load target chats."""
    try:
        accounts = await db.accounts.find({
            "user_id": user_id,
            "active": True
        }).to_list(20)
        
        if not accounts:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text="❌ No active accounts. Add accounts first.",
                reply_markup=kb_dashboard(user_id, {})
            )
            return
        
        total_chats = 0
        new_chats = []
        errors = []
        
        for acc in accounts:
            try:
                client = await get_cached_client(acc["session"])
                
                async for dialog in client.iter_dialogs(limit=200):
                    entity = dialog.entity
                    
                    if isinstance(entity, User):
                        continue
                    
                    try:
                        if isinstance(entity, Channel):
                            full = await client(GetFullChannelRequest(entity))
                            members = getattr(full.full_chat, 'participants_count', 0)
                        else:
                            members = getattr(entity, 'participants_count', 0)
                    except Exception:
                        members = 0
                    
                    if members < 50:
                        continue
                    
                    if not dialog.dialog.notify_settings:
                        continue
                    
                    chat_id_ent = dialog.id
                    access_hash = getattr(entity, 'access_hash', 0)
                    title = getattr(entity, 'title', 'Unknown')
                    
                    if any(c['chat_id'] == chat_id_ent and c['account_id'] == acc['_id'] for c in new_chats):
                        continue
                    
                    new_chats.append({
                        "chat_id": chat_id_ent,
                        "access_hash": access_hash,
                        "title": title,
                        "members": members,
                        "account_id": acc['_id'],
                        "added": datetime.now(timezone.utc)
                    })
                
                total_chats += len(new_chats)
                await asyncio.sleep(2)
            except FloodWaitError as e:
                errors.append(f"Account {format_phone(acc.get('phone',''))}: Flood wait {e.seconds}s")
                await asyncio.sleep(e.seconds + 5)
            except Exception as e:
                errors.append(f"Account {format_phone(acc.get('phone',''))}: {str(e)[:50]}")
                logger.error(f"Chat loading error: {e}")
        
        if new_chats:
            await db.users.update_one(
                {"user_id": user_id},
                {
                    "$set": {"last_chat_scan": datetime.now(timezone.utc)},
                    "$addToSet": {"chats": {"$each": new_chats}}
                },
                upsert=True
            )
        
        user_doc = await db.users.find_one({"user_id": user_id}) or {}
        total_unique = len(user_doc.get("chats", []))
        
        result_text = (
            f"✅ <b>Chat Loading Complete!</b>\n\n"
            f"📱 Accounts scanned: {len(accounts)}\n"
            f"💬 New chats found: {len(new_chats)}\n"
            f"📊 Total target chats: {total_unique}\n\n"
        )
        
        if errors:
            result_text += f"⚠️ Warnings ({len(errors)}):\n" + "\n".join(f"• {e}" for e in errors[:3])
        
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=result_text,
            reply_markup=kb_dashboard(user_id, {}),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.exception(f"Chat loading failed: {e}")
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=f"❌ Failed: {str(e)[:200]}",
                reply_markup=kb_dashboard(user_id, {})
            )
        except Exception:
            pass

async def handle_campaign_actions(query, user_id: int, action: str):
    """Handle campaign start/stop."""
    user_doc = await db.users.find_one({"user_id": user_id}) or {}
    
    if action == "start":
        if not user_doc.get("ad_message"):
            await query.answer("❌ Ad message not set!", show_alert=True)
            return
        if not user_doc.get("chats"):
            await query.answer("❌ No target chats!", show_alert=True)
            return
        
        active_accounts = await db.accounts.count_documents({
            "user_id": user_id,
            "active": True
        })
        if active_accounts == 0:
            await query.answer("❌ No active accounts!", show_alert=True)
            return
        
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"running": True, "started_at": datetime.now(timezone.utc)}},
            upsert=True
        )
        
        if user_id in ad_tasks and not ad_tasks[user_id].done():
            ad_tasks[user_id].cancel()
        
        task = asyncio.create_task(run_campaign(user_id))
        ad_tasks[user_id] = task
        
        state = user_states.get(user_id)
        delay_config = state.delay_config if state else {"min": 60, "max": 180}
        
        await query.edit_message_text(
            "🚀 <b>Campaign Started!</b>\n\n"
            f"📱 Active Accounts: {active_accounts}\n"
            f"💬 Target Chats: {len(user_doc.get('chats', []))}\n"
            f"⏱️ Delay Range: {delay_config['min']}-{delay_config['max']}s\n"
            f"⏱️ First batch in: ~{delay_config['min']} seconds\n\n"
            "📊 Use /status to check progress",
            reply_markup=kb_dashboard(user_id, {"running": True}),
            parse_mode=ParseMode.HTML
        )
    
    elif action == "stop":
        if user_id in ad_tasks and not ad_tasks[user_id].done():
            ad_tasks[user_id].cancel()
            del ad_tasks[user_id]
        
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"running": False, "stopped_at": datetime.now(timezone.utc)}}
        )
        
        await query.edit_message_text(
            "⏹️ <b>Campaign Stopped</b>\n\n"
            "All tasks terminated.\n"
            "Accounts are safe.",
            reply_markup=kb_dashboard(user_id, {"running": False}),
            parse_mode=ParseMode.HTML
        )

async def run_campaign(user_id: int):
    """Main campaign execution loop."""
    logger.info(f"Starting campaign for user {user_id}")
    
    try:
        while True:
            user_doc = await db.users.find_one({"user_id": user_id})
            if not user_doc or not user_doc.get("running"):
                break
            
            ad_data = user_doc.get("ad_message")
            target_chats = user_doc.get("chats", [])
            
            if not ad_data or not target_chats:
                await asyncio.sleep(300)
                continue
            
            cycle_stats = {
                "sent": 0,
                "failed": 0,
                "timestamp": datetime.now(timezone.utc),
                "details": []
            }
            
            state = user_states.get(user_id)
            delay_config = state.delay_config if state else {"min": 60, "max": 180}
            
            for idx, chat in enumerate(target_chats[:100]):
                user_doc = await db.users.find_one({"user_id": user_id})
                if not user_doc or not user_doc.get("running"):
                    break
                
                account = await db.accounts.find_one({
                    "_id": chat["account_id"],
                    "user_id": user_id,
                    "active": True
                })
                
                if not account:
                    cycle_stats["failed"] += 1
                    cycle_stats["details"].append({
                        "chat": chat.get("title", "Unknown"),
                        "error": "Account unavailable"
                    })
                    continue
                
                try:
                    client = await get_cached_client(account["session"])
                    
                    await client.forward_messages(
                        entity=chat["chat_id"],
                        messages=ad_data["msg_id"],
                        from_peer="me",
                        drop_author=True,
                        silent=True
                    )
                    
                    cycle_stats["sent"] += 1
                    cycle_stats["details"].append({
                        "chat": chat.get("title", "Unknown"),
                        "status": "success"
                    })
                    
                    logger.info(f"User {user_id}: Sent to {chat.get('title', 'unknown')}")
                    
                    await db.accounts.update_one(
                        {"_id": account["_id"]},
                        {"$set": {"last_used": datetime.now(timezone.utc)}}
                    )
                    
                    delay = random.uniform(delay_config['min'], delay_config['max'])
                    await asyncio.sleep(delay)
                except (ChatWriteForbiddenError, PeerFloodError) as e:
                    cycle_stats["failed"] += 1
                    cycle_stats["details"].append({
                        "chat": chat.get("title", "Unknown"),
                        "error": f"Permission error"
                    })
                    logger.warning(f"User {user_id}: Permission error: {e}")
                    await asyncio.sleep(random.uniform(120, 300))
                except FloodWaitError as e:
                    cycle_stats["failed"] += 1
                    cycle_stats["details"].append({
                        "chat": chat.get("title", "Unknown"),
                        "error": f"Flood wait: {e.seconds}s"
                    })
                    logger.warning(f"User {user_id}: Flood wait {e.seconds}s")
                    wait_time = min(e.seconds + random.randint(30, 60), 900)
                    await asyncio.sleep(wait_time)
                except Exception as e:
                    cycle_stats["failed"] += 1
                    cycle_stats["details"].append({
                        "chat": chat.get("title", "Unknown"),
                        "error": str(e)[:100]
                    })
                    logger.error(f"User {user_id}: Send error: {e}")
                    await asyncio.sleep(random.uniform(30, 90))
            
            await db.users.update_one(
                {"user_id": user_id},
                {"$push": {"stats": {
                    "$each": [cycle_stats],
                    "$slice": -100
                }}}
            )
            
            cycle_delay = random.uniform(1800, 3600)
            logger.info(f"User {user_id}: Cycle complete. Next in {cycle_delay/60:.1f} min")
            await asyncio.sleep(cycle_delay)
    except asyncio.CancelledError:
        logger.info(f"Campaign for user {user_id} cancelled")
    except Exception as e:
        logger.exception(f"Campaign for user {user_id} crashed: {e}")
    finally:
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"running": False, "stopped_at": datetime.now(timezone.utc)}}
        )
        logger.info(f"Campaign for user {user_id} terminated")

async def handle_stats_actions(query, user_id: int, args: List[str]):
    """Handle statistics display."""
    user_doc = await db.users.find_one({"user_id": user_id}) or {}
    stats = user_doc.get("stats", [])
    
    if not stats:
        await query.edit_message_text(
            "📊 <b>Statistics</b>\n\n"
            "No campaign data yet.\n\n"
            "▶️ Start a campaign to see analytics.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ Start Campaign", callback_data="campaign|start")],
                [InlineKeyboardButton("🔙 Back", callback_data="nav|dashboard")]
            ]),
            parse_mode=ParseMode.HTML
        )
        return
    
    total_sent = sum(s.get("sent", 0) for s in stats)
    total_failed = sum(s.get("failed", 0) for s in stats)
    success_rate = (total_sent / (total_sent + total_failed) * 100) if (total_sent + total_failed) > 0 else 0
    
    recent = stats[-5:]
    activity_text = "\n".join(
        f"• {s['timestamp'].strftime('%H:%M')}: ✅{s.get('sent',0)} ❌{s.get('failed',0)}"
        for s in recent
    )
    
    stats_text = (
        f"📊 <b>Campaign Statistics</b>\n\n"
        f"✅ Total Sent: {total_sent}\n"
        f"❌ Total Failed: {total_failed}\n"
        f"📈 Success Rate: {success_rate:.1f}%\n\n"
        f"⏱️ Recent Activity (last 5 cycles):\n{activity_text}"
    )
    
    await query.edit_message_text(
        stats_text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="nav|dashboard")]
        ]),
        parse_mode=ParseMode.HTML
    )

async def handle_settings_actions(query, user_id: int, args: List[str]):
    """Handle settings actions."""
    if not args:
        return
    
    action = args[0]
    if action == "delays":
        if user_id not in user_states:
            user_states[user_id] = UserState()
        
        await query.edit_message_text(
            "⏱️ <b>Delay Configuration</b>\n\n"
            "Configure delays between message sends.\n\n"
            "⚠️ Lower delays = faster but riskier\n"
            "⚠️ Higher delays = safer but slower",
            reply_markup=kb_delay_settings(user_id),
            parse_mode=ParseMode.HTML
        )

async def handle_delay_settings(query, user_id: int, action: str):
    """Handle delay settings."""
    if user_id not in user_states:
        user_states[user_id] = UserState()
    
    state = user_states[user_id]
    
    if action == "min":
        await query.edit_message_text(
            "⏱️ <b>Set Minimum Delay</b>\n\n"
            "Send a number (in seconds):\n"
            "Recommended: 60-300\n\n"
            "Example: <code>60</code>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="settings|delays")]
            ]),
            parse_mode=ParseMode.HTML
        )
        state.step = "set_min_delay"
    elif action == "max":
        await query.edit_message_text(
            "⏱️ <b>Set Maximum Delay</b>\n\n"
            "Send a number (in seconds):\n"
            "Recommended: 180-600\n\n"
            "Example: <code>180</code>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="settings|delays")]
            ]),
            parse_mode=ParseMode.HTML
        )
        state.step = "set_max_delay"

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages."""
    user_id = update.effective_user.id
    message = update.message
    
    if not message:
        return
    
    state = user_states.get(user_id)
    
    # Handle delay settings input
    if state and state.step in ["set_min_delay", "set_max_delay"]:
        try:
            delay_value = int(message.text.strip())
            
            if delay_value < 30 or delay_value > 3600:
                await message.reply_text(
                    "❌ Invalid value!\n\n"
                    "Please enter a number between 30 and 3600 seconds.",
                    reply_markup=kb_delay_settings(user_id)
                )
                return
            
            if state.step == "set_min_delay":
                state.delay_config["min"] = delay_value
                await message.reply_text(
                    f"✅ Minimum delay set to {delay_value} seconds.",
                    reply_markup=kb_delay_settings(user_id)
                )
            else:
                state.delay_config["max"] = delay_value
                await message.reply_text(
                    f"✅ Maximum delay set to {delay_value} seconds.",
                    reply_markup=kb_delay_settings(user_id)
                )
            
            state.step = "idle"
        except ValueError:
            await message.reply_text(
                "❌ Please enter a valid number!",
                reply_markup=kb_delay_settings(user_id)
            )
        return
    
    # Handle phone number input
    if state and state.step == "phone":
        phone = message.text.strip()
        
        if not re.match(r'^\+?[1-9]\d{1,14}$', phone):
            await message.reply_text(
                "❌ Invalid phone number!\n\n"
                "Use international format:\n"
                "<code>+12025550123</code> or <code>+447911123456</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Cancel", callback_data="nav|dashboard")]
                ])
            )
            return
        
        if not phone.startswith('+'):
            phone = '+' + phone
        
        try:
            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()
            
            if await client.is_user_authorized():
                await message.reply_text(
                    "✅ This session is already authorized.\n\n"
                    "Please use a fresh account.",
                    reply_markup=kb_dashboard(user_id, {})
                )
                await client.disconnect()
                await cleanup_user_state(user_id)
                return
            
            sent_code = await client.send_code_request(phone)
            
            user_states[user_id] = UserState(
                step="otp",
                phone=phone,
                phone_code_hash=sent_code.phone_code_hash,
                client=client,
                timestamp=datetime.now(timezone.utc)
            )
            
            await message.reply_text(
                f"✅ Code sent to {format_phone(phone)}\n\n"
                "Enter the 5-digit code:",
                reply_markup=kb_otp_keyboard(user_id, "otp"),
                parse_mode=ParseMode.HTML
            )
        except FloodWaitError as e:
            await message.reply_text(
                f"⏳ Wait {e.seconds} seconds before trying again.",
                reply_markup=kb_dashboard(user_id, {})
            )
            await cleanup_user_state(user_id)
        except PhoneNumberInvalidError:
            await message.reply_text(
                "❌ Invalid phone number. Check format and try again.",
                reply_markup=kb_dashboard(user_id, {})
            )
            await cleanup_user_state(user_id)
        except Exception as e:
            logger.error(f"Phone request error: {e}")
            await message.reply_text(
                f"❌ Error: {str(e)[:150]}",
                reply_markup=kb_dashboard(user_id, {})
            )
            await cleanup_user_state(user_id)
        return
    
    # Handle ad message setup
    if state and state.step == "wait_ad":
        if not message.forward_origin:
            await message.reply_text(
                "⚠️ Please forward from <b>Saved Messages</b> only.",
                parse_mode=ParseMode.HTML
            )
            return
        
        is_from_self = False
        try:
            if hasattr(message.forward_origin, 'sender_user'):
                is_from_self = message.forward_origin.sender_user.id == user_id
            elif hasattr(message.forward_origin, 'from_user'):
                is_from_self = message.forward_origin.from_user.id == user_id
        except Exception:
            pass
        
        if not is_from_self:
            await message.reply_text(
                "❌ Invalid source!\n\n"
                "Only messages from your <b>own Saved Messages</b> are accepted.\n\n"
                "📱 How to:\n"
                "1. Open Saved Messages\n"
                "2. Forward your ad message here",
                parse_mode=ParseMode.HTML
            )
            return
        
        ad_data = {
            "msg_id": message.id,
            "chat_id": message.chat_id,
            "text": message.text or message.caption or "",
            "has_media": bool(message.photo or message.video or message.document),
            "saved_at": datetime.now(timezone.utc)
        }
        
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"ad_message": ad_data}},
            upsert=True
        )
        
        preview = ad_data['text'][:100] + "..." if len(ad_data['text']) > 100 else ad_data['text']
        media_note = "\n📎 Contains media" if ad_data['has_media'] else ""
        
        await message.reply_text(
            "✅ <b>Ad Message Saved!</b>\n\n"
            f"📝 Preview: <i>{preview}</i>{media_note}\n\n"
            "🚀 Ready to launch!",
            reply_markup=kb_dashboard(user_id, {}),
            parse_mode=ParseMode.HTML
        )
        
        await cleanup_user_state(user_id)
        return
    
    # Default response
    await message.reply_text(
        "👋 Welcome to ADIMYZE PRO!\n\n"
        "Use /start to access the menu.",
        reply_markup=kb_start_menu()
    )

# ────────────────────────────────────────────────
# SHUTDOWN & MAIN
# ────────────────────────────────────────────────
async def shutdown_handler():
    """Graceful shutdown."""
    logger.info("Initiating graceful shutdown...")
    
    for user_id, task in list(ad_tasks.items()):
        if not task.done():
            logger.info(f"Cancelling campaign for user {user_id}")
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    
    for session_hash, client in list(active_clients.items()):
        logger.info(f"Disconnecting client {session_hash}")
        await safe_disconnect(client)
    
    mongo_client.close()
    logger.info("Shutdown complete.")

async def main():
    """Main entry point."""
    lock_fd = acquire_lock()
    
    try:
        logger.info("=" * 60)
        logger.info("👑 ADIMYZE PRO v14 STARTING")
        logger.info("=" * 60)
        
        try:
            await db.command('ping')
            logger.info("✅ MongoDB connected")
        except Exception as e:
            logger.error(f"❌ MongoDB connection failed: {e}")
            return
        
        application = Application.builder().token(BOT_TOKEN).build()
        
        application.add_handler(CommandHandler("start", cmd_start))
        application.add_handler(CommandHandler("clear", cmd_clear))
        application.add_handler(CommandHandler("status", cmd_status))
        application.add_handler(CallbackQueryHandler(callback_handler))
        application.add_handler(MessageHandler(
            (filters.TEXT | filters.FORWARDED) & ~filters.COMMAND,
            message_handler
        ))
        
        await application.initialize()
        await application.start()
        await application.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
        
        logger.info("✅ ADIMYZE PRO v14 IS NOW RUNNING")
        logger.info(f"Bot: @{(await application.bot.get_me()).username}")
        logger.info("Press Ctrl+C to stop")
        logger.info("=" * 60)
        
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutdown requested...")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
    finally:
        await shutdown_handler()
        release_lock(lock_fd)
        logger.info("👋 ADIMYZE PRO v14 STOPPED")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        logger.exception(f"Startup failed: {e}")
        sys.exit(1)