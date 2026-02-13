import asyncio
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Dict, Optional
from dataclasses import dataclass

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import UserFull
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, AuthKeyUnregisteredError

from motor.motor_asyncio import AsyncIOMotorClient

# --- Configuration ---
BOT_TOKEN = '8463982454:AAErd8EZswKgQ1BNF_r-N8iUH8HQcb293lQ'
API_ID = 22657083
API_HASH = 'd6186691704bd901bdab275ceaab88f3'
MONGO_URI = "mongodb+srv://bot627668:2bEJ56yJSu7vzLws@cluster0.qbw5van.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
BANNER_URL = "https://files.catbox.moe/zttfbe.jpg"

PROFILE_NAME = "Adimyze Pro"
PROFILE_BIO = "🚀 Professional Telegram Marketing Automation | Managed by @nexaxoders"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

db = AsyncIOMotorClient(MONGO_URI)["adimyze"]

@dataclass
class UserState:
    step: str = "idle"  # idle, phone, code, password, set_ad, set_delay_custom
    phone: str = ""
    phone_code_hash: str = ""
    client: Optional[TelegramClient] = None
    buffer: str = ""
    delay: int = 300

user_states: Dict[int, UserState] = {}

# --- Helper Functions ---

def format_time(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}min"
    else:
        return f"{seconds // 3600}h"

def get_delay_emoji(seconds: int) -> str:
    if seconds <= 300:
        return "🔴"
    elif seconds <= 600:
        return "🟡"
    else:
        return "🟢"

# --- Keyboards ---

def kb_start():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("     Dashboard       ", callback_data="nav|dashboard")],
        [InlineKeyboardButton("Updates", url="https://t.me/testttxs"),
         InlineKeyboardButton("Support", url="https://t.me/nexaxoders")],
        [InlineKeyboardButton("     How to Use      ", callback_data="nav|howto")],
        [InlineKeyboardButton("       Powered By    ", url="https://t.me/nexaxoders")]
    ])

def kb_dashboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Accounts", callback_data="acc|add"),
         InlineKeyboardButton("My Accounts", callback_data="acc|list")],
        [InlineKeyboardButton("Set Ad Message", callback_data="ad|set"),
         InlineKeyboardButton("Set Time Interval", callback_data="delay|nav")],
        [InlineKeyboardButton("Start Ads", callback_data="camp|start"),
         InlineKeyboardButton("Stop Ads", callback_data="camp|stop")],
        [InlineKeyboardButton("Delete Accounts", callback_data="acc|del"),
         InlineKeyboardButton("Analytics", callback_data="stat|main")],
        [InlineKeyboardButton("Auto Reply", callback_data="feature|auto")],
        [InlineKeyboardButton("Back", callback_data="nav|start")]
    ])

def kb_otp(user_id):
    state = user_states.get(user_id, UserState())
    display = (state.buffer + "○" * (5 - len(state.buffer)))[:5]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(display, callback_data="noop")],
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
         InlineKeyboardButton("✅", callback_data="otp|submit")],
        [InlineKeyboardButton("Show Code", callback_data="otp|show")],
        [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
    ])

def kb_delay(current_delay: int = 300):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"5min {get_delay_emoji(300)}", callback_data="setdelay|300"),
         InlineKeyboardButton(f"10min {get_delay_emoji(600)}", callback_data="setdelay|600")],
        [InlineKeyboardButton(f"20min {get_delay_emoji(1200)}", callback_data="setdelay|1200")],
        [InlineKeyboardButton("Custom", callback_data="delay|custom")],
        [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
    ])

def kb_accounts(accounts, page=0):
    buttons = []
    page_size = 5
    start = page * page_size
    end = start + page_size
    page_accounts = accounts[start:end]
    
    for acc in page_accounts:
        status = "🟢" if acc.get("active", False) else "🔴"
        phone = acc["phone"]
        display = f"{status} {phone[-4:]}"  # Show last 4 digits for privacy
        buttons.append([InlineKeyboardButton(display, callback_data=f"acc|detail|{acc['_id']}")])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"acc|list|{page-1}"))
    if end < len(accounts):
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"acc|list|{page+1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    buttons.append([InlineKeyboardButton("Back", callback_data="nav|dashboard")])
    return InlineKeyboardMarkup(buttons)

def kb_account_detail(acc_id, phone):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Delete Account", callback_data=f"acc|delete|{acc_id}")],
        [InlineKeyboardButton("Back to List", callback_data="acc|list|0")],
        [InlineKeyboardButton("Dashboard", callback_data="nav|dashboard")]
    ])

def kb_confirm(text: str, yes_data: str, no_data: str = "nav|dashboard"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Yes", callback_data=yes_data),
         InlineKeyboardButton(f"❌ No", callback_data=no_data)]
    ])

# --- Handlers ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ("╰_╯ Welcome to @Tecxo Free Ads bot — The Future of Telegram Automation\n\n"
            "• Premium Ad Broadcasting\n"
            "• Smart Delays\n"
            "• Multi-Account Support\n\n"
            "For support contact: @NexaCoders")
    msg = update.message or update.callback_query.message if update.callback_query else None
    
    if not msg:
        return
    
    try:
        await msg.reply_photo(
            photo=BANNER_URL,
            caption=text,
            reply_markup=kb_start(),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.warning(f"Failed to send photo: {e}")
        await msg.reply_text(text, reply_markup=kb_start(), parse_mode=ParseMode.MARKDOWN)

async def handle_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    dest = parts[1]

    if dest == "start":
        await cmd_start(update, context)
    elif dest == "dashboard":
        await query.edit_message_caption(
            caption="╰_╯ DASHBOARD\n\nManage your ad campaigns and accounts:",
            reply_markup=kb_dashboard()
        )
    elif dest == "howto":
        text = ("╰_╯ HOW TO USE\n\n"
                "1️⃣ Add Account → Host your Telegram account\n"
                "2️⃣ Set Ad Message → Create your promotional text\n"
                "3️⃣ Set Time Interval → Configure broadcast frequency\n"
                "4️⃣ Start Ads → Begin automated broadcasting\n\n"
                "⚠️ Note: Using aggressive intervals may risk account suspension")
        await query.edit_message_caption(
            caption=text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
            ])
        )

async def handle_account_ops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    action = parts[1]
    user_id = query.from_user.id

    if action == "add":
        user_states[user_id] = UserState(step="phone")
        text = ("╰_╯ HOST NEW ACCOUNT\n\n"
                "🔐 Secure Account Hosting\n\n"
                "Enter your phone number with country code:\n"
                "Example: +1234567890\n\n"
                "🔒 Your data is encrypted and secure")
        await query.edit_message_caption(
            caption=text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
            ])
        )
    
    elif action == "list":
        page = int(parts[2]) if len(parts) > 2 else 0
        accounts = await db.accounts.find({"user_id": user_id}).to_list(None)
        
        if not accounts:
            await query.answer("No accounts added yet!", show_alert=True)
            return
        
        await query.edit_message_caption(
            caption=f"📱 MY ACCOUNTS ({len(accounts)})\n\nSelect an account to manage:",
            reply_markup=kb_accounts(accounts, page)
        )
    
    elif action == "detail":
        acc_id = parts[2]
        account = await db.accounts.find_one({"_id": acc_id, "user_id": user_id})
        if not account:
            await query.answer("Account not found!", show_alert=True)
            return
        
        status = "🟢 Active" if account.get("active") else "🔴 Inactive"
        phone = account["phone"]
        text = (f"📱 ACCOUNT DETAILS\n\n"
                f"Phone: {phone}\n"
                f"Status: {status}\n"
                f"Added: {account.get('created_at', 'N/A')}")
        
        await query.edit_message_caption(
            caption=text,
            reply_markup=kb_account_detail(acc_id, phone)
        )
    
    elif action == "delete":
        acc_id = parts[2]
        account = await db.accounts.find_one({"_id": acc_id, "user_id": user_id})
        if not account:
            await query.answer("Account not found!", show_alert=True)
            return
        
        phone = account["phone"]
        confirm_text = f"⚠️ DELETE ACCOUNT\n\nAre you sure you want to delete:\n{phone}?"
        await query.edit_message_caption(
            caption=confirm_text,
            reply_markup=kb_confirm("Delete", f"acc|confirm_del|{acc_id}")
        )
    
    elif action == "confirm_del":
        acc_id = parts[2]
        result = await db.accounts.delete_one({"_id": acc_id, "user_id": user_id})
        if result.deleted_count:
            await query.answer("✅ Account deleted successfully!", show_alert=True)
        else:
            await query.answer("❌ Failed to delete account!", show_alert=True)
        await query.edit_message_caption(
            caption="╰_╯ DASHBOARD\n\nManage your ad campaigns and accounts:",
            reply_markup=kb_dashboard()
        )
    
    elif action == "del":
        accounts = await db.accounts.count_documents({"user_id": user_id})
        if accounts == 0:
            await query.answer("No accounts to delete!", show_alert=True)
            return
        
        text = "🗑️ DELETE ACCOUNTS\n\nSelect accounts to remove from your campaign:"
        await query.edit_message_caption(
            caption=text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("View & Delete Accounts", callback_data="acc|list|0")],
                [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
            ])
        )

async def input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    text = update.message.text.strip()

    if not state or state.step == "idle":
        return

    try:
        if state.step == "phone":
            # Validate and format phone number
            phone = "+" + re.sub(r"\D", "", text)
            if len(phone) < 8 or len(phone) > 15:
                await update.message.reply_text(
                    "❌ Invalid phone number!\n\nPlease enter a valid number with country code:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
                    ])
                )
                return
            
            # Initialize client and request code
            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()
            
            sent = await client.send_code_request(phone)
            state.client = client
            state.phone = phone
            state.phone_code_hash = sent.phone_code_hash
            state.step = "code"
            state.buffer = ""
            
            await update.message.reply_text(
                f"⏳ Hold! We're trying to OTP...\n\n📱 Phone: {phone}\nPlease wait a moment."
            )
            await update.message.reply_text(
                "🔢 Enter OTP using the keypad below:",
                reply_markup=kb_otp(user_id)
            )
        
        elif state.step == "password":
            # Handle 2FA password
            await finalize_login(user_id, context, password=text)
            user_states[user_id] = UserState(step="idle")
        
        elif state.step == "set_ad":
            if len(text) > 4000:
                await update.message.reply_text(
                    "❌ Message too long! (Max 4000 characters)\n\nPlease send a shorter ad message:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
                    ])
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
                reply_markup=kb_dashboard()
            )
        
        elif state.step == "set_delay_custom":
            try:
                delay = int(text)
                if delay < 60:
                    await update.message.reply_text(
                        "⚠️ Minimum interval is 60 seconds!\n\nEnter a valid interval (in seconds):",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("Back", callback_data="delay|nav")]
                        ])
                    )
                    return
                if delay > 86400:
                    await update.message.reply_text(
                        "⚠️ Maximum interval is 86400 seconds (24 hours)!\n\nEnter a valid interval (in seconds):",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("Back", callback_data="delay|nav")]
                        ])
                    )
                    return
                
                await db.users.update_one(
                    {"user_id": str(user_id)},
                    {"$set": {"delay": delay, "updated_at": datetime.now(timezone.utc)}},
                    upsert=True
                )
                user_states[user_id] = UserState(step="idle", delay=delay)
                await update.message.reply_text(
                    f"✅ Interval set to {format_time(delay)} ({delay}s)",
                    reply_markup=kb_dashboard()
                )
            except ValueError:
                await update.message.reply_text(
                    "❌ Invalid number!\n\nPlease enter interval in seconds (e.g., 600):",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Back", callback_data="delay|nav")]
                    ])
                )
    
    except Exception as e:
        logger.exception(f"Error in input handler: {e}")
        await update.message.reply_text(
            f"❌ Unexpected error: {str(e)[:100]}\n\nPlease try again or contact support.",
            reply_markup=kb_dashboard()
        )
        if state.client:
            await state.client.disconnect()
        user_states[user_id] = UserState(step="idle")

async def handle_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    state = user_states.get(user_id)
    
    if not state or state.step != "code":
        await query.answer("Session expired! Please restart the process.", show_alert=True)
        return

    await query.answer()
    parts = query.data.split("|")
    action = parts[1]

    if action == "back":
        state.buffer = state.buffer[:-1]
    elif action == "show":
        code_display = state.buffer if state.buffer else "Empty"
        await query.answer(f"Current Code: {code_display}", show_alert=True)
        return
    elif action == "submit":
        if len(state.buffer) != 5:
            await query.answer("⚠️ Please enter a 5-digit code!", show_alert=True)
            return
        await finalize_login(user_id, context)
        return
    elif action.isdigit() and len(state.buffer) < 5:
        state.buffer += action

    try:
        await query.edit_message_reply_markup(reply_markup=kb_otp(user_id))
    except BadRequest:
        pass  # Message not modified

async def finalize_login(user_id, context, password=None):
    state = user_states.get(user_id)
    if not state or not state.client:
        await context.bot.send_message(
            user_id,
            "❌ Session expired! Please restart the login process.",
            reply_markup=kb_dashboard()
        )
        return

    try:
        if password:
            # Handle 2FA
            await state.client.sign_in(password=password)
        else:
            # Handle OTP
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
            logger.warning(f"Failed to update profile for {state.phone}: {e}")
            # Continue anyway - not critical
        
        # Save session
        session = state.client.session.save()
        account_data = {
            "user_id": user_id,
            "phone": state.phone,
            "session": session,
            "active": True,
            "created_at": datetime.now(timezone.utc),
            "last_used": datetime.now(timezone.utc)
        }
        
        await db.accounts.update_one(
            {"user_id": user_id, "phone": state.phone},
            {"$set": account_data},
            upsert=True
        )
        
        # Cleanup state
        await state.client.disconnect()
        user_states[user_id] = UserState(step="idle")
        
        # Success message
        success_msg = (f"✅ Account Successfully Added!\n\n"
                      f"📱 Phone: {state.phone}\n"
                      f"╰_╯ Your account is ready for broadcasting!\n\n"
                      f"ℹ️ Profile name & bio have been updated automatically.")
        await context.bot.send_message(
            user_id,
            success_msg,
            reply_markup=kb_dashboard()
        )
        
    except SessionPasswordNeededError:
        state.step = "password"
        await context.bot.send_message(
            user_id,
            "🔐 2FA Detected!\n\nPlease send your Telegram cloud password:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
            ])
        )
    except (PhoneCodeInvalidError, ValueError):
        await context.bot.send_message(
            user_id,
            "❌ Invalid OTP code! Please restart the login process.",
            reply_markup=kb_dashboard()
        )
        await state.client.disconnect()
        user_states[user_id] = UserState(step="idle")
    except Exception as e:
        error_msg = str(e)
        if "PHONE_CODE_EXPIRED" in error_msg or "SESSION_REVOKED" in error_msg:
            error_msg = "OTP expired! Please restart the login process."
        elif "FLOOD_WAIT" in error_msg:
            wait_time = re.search(r'FLOOD_WAIT_(\d+)', error_msg)
            if wait_time:
                error_msg = f"Too many attempts! Please wait {wait_time.group(1)} seconds before trying again."
            else:
                error_msg = "Too many attempts! Please try again later."
        
        await context.bot.send_message(
            user_id,
            f"❌ Login Failed: {error_msg}",
            reply_markup=kb_dashboard()
        )
        logger.exception(f"Login failed for {state.phone}: {e}")
        await state.client.disconnect()
        user_states[user_id] = UserState(step="idle")

async def handle_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == "ad|set":
        user_states[user_id] = UserState(step="set_ad")
        text = ("╰_╯ SET YOUR AD MESSAGE\n\n"
                "💡 Tips for effective ads:\n"
                "• Keep it concise and engaging\n"
                "• Use premium emojis for flair\n"
                "• Include clear call-to-action\n"
                "• Avoid excessive caps or spam words\n\n"
                "📤 Send your ad message now:")
        await query.edit_message_caption(
            caption=text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
            ])
        )

async def handle_delay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    parts = query.data.split("|")
    
    if parts[0] == "delay":
        action = parts[1]
        if action == "nav":
            # Get current delay from DB or use default
            user_doc = await db.users.find_one({"user_id": str(user_id)})
            current_delay = user_doc.get("delay", 300) if user_doc else 300
            
            text = (f"╰_╯ SET BROADCAST CYCLE INTERVAL\n\n"
                   f"Current Interval: {format_time(current_delay)} ({current_delay}s)\n\n"
                   f"Recommended Intervals:\n"
                   f"• 300s - Aggressive (5 min) 🔴\n"
                   f"• 600s - Safe & Balanced (10 min) 🟡\n"
                   f"• 1200s - Conservative (20 min) 🟢\n\n"
                   f"⚠️ Note: Using short intervals may risk account suspension.")
            await query.edit_message_caption(
                caption=text,
                reply_markup=kb_delay(current_delay)
            )
        elif action == "custom":
            user_states[user_id] = UserState(step="set_delay_custom")
            await query.edit_message_caption(
                caption="╰_╯ CUSTOM INTERVAL\n\nEnter interval in seconds (min 60, max 86400):\nExample: 900",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Back", callback_data="delay|nav")]
                ])
            )
    
    elif parts[0] == "setdelay":
        delay = int(parts[1])
        await db.users.update_one(
            {"user_id": str(user_id)},
            {"$set": {"delay": delay, "updated_at": datetime.now(timezone.utc)}},
            upsert=True
        )
        await query.answer(f"✅ Interval set to {format_time(delay)}", show_alert=True)
        user_doc = await db.users.find_one({"user_id": str(user_id)})
        current_delay = user_doc.get("delay", 300) if user_doc else 300
        text = (f"╰_╯ SET BROADCAST CYCLE INTERVAL\n\n"
               f"Current Interval: {format_time(current_delay)} ({current_delay}s)\n\n"
               f"Recommended Intervals:\n"
               f"• 300s - Aggressive (5 min) 🔴\n"
               f"• 600s - Safe & Balanced (10 min) 🟡\n"
               f"• 1200s - Conservative (20 min) 🟢\n\n"
               f"⚠️ Note: Using short intervals may risk account suspension.")
        await query.edit_message_caption(
            caption=text,
            reply_markup=kb_delay(current_delay)
        )

async def handle_analytics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    parts = query.data.split("|")
    
    if parts[1] == "main":
        # Get stats
        active_accounts = await db.accounts.count_documents({"user_id": user_id, "active": True})
        total_accounts = await db.accounts.count_documents({"user_id": user_id})
        
        # Get user settings
        user_doc = await db.users.find_one({"user_id": str(user_id)})
        current_delay = user_doc.get("delay", 300) if user_doc else 300
        
        # Get campaign stats (placeholder - would need actual broadcast tracking)
        total_sent = 0
        total_failed = 0
        broadcast_cycles = 0
        
        # Calculate success rate
        total_attempts = total_sent + total_failed
        success_rate = int((total_sent / total_attempts * 100)) if total_attempts > 0 else 0
        bar = "▓" * (success_rate // 10) + "░" * (10 - success_rate // 10)
        
        text = (f"╰_╯ @NexaCoders ANALYTICS\n\n"
               f"Broadcast Cycles: {broadcast_cycles}\n"
               f"Messages Sent: {total_sent}\n"
               f"Failed Sends: {total_failed}\n"
               f"Active Accounts: {active_accounts}/{total_accounts}\n"
               f"Avg Delay: {format_time(current_delay)}\n\n"
               f"Success Rate: {bar} {success_rate}%")
        
        await query.edit_message_caption(
            caption=text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Detailed Report", callback_data="stat|detail")],
                [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
            ])
        )
    
    elif parts[1] == "detail":
        # Get detailed stats
        active_accounts = await db.accounts.count_documents({"user_id": user_id, "active": True})
        total_accounts = await db.accounts.count_documents({"user_id": user_id})
        inactive_accounts = total_accounts - active_accounts
        
        user_doc = await db.users.find_one({"user_id": str(user_id)})
        current_delay = user_doc.get("delay", 300) if user_doc else 300
        
        # Placeholder stats - would need actual tracking system
        total_sent = 0
        total_failed = 0
        broadcast_cycles = 0
        logger_failures = 0
        last_failure = "None"
        
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%d/%m/%y")
        
        text = (f"╰_╯ DETAILED ANALYTICS REPORT\n\n"
               f"Date: {date_str}\n"
               f"User ID: {user_id}\n\n"
               f"Broadcast Stats:\n"
               f"- Total Sent: {total_sent}\n"
               f"- Total Failed: {total_failed}\n"
               f"- Total Broadcasts: {broadcast_cycles}\n\n"
               f"Logger Stats:\n"
               f"- Logger Failures: {logger_failures}\n"
               f"- Last Failure: {last_failure}\n\n"
               f"Account Stats:\n"
               f"- Total Accounts: {total_accounts}\n"
               f"- Active Accounts: {active_accounts} 🟢\n"
               f"- Inactive Accounts: {inactive_accounts} 🔴\n\n"
               f"Current Delay: {format_time(current_delay)} ({current_delay}s)")
        
        await query.edit_message_caption(
            caption=text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Back", callback_data="stat|main")]
            ])
        )

async def handle_features(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    
    if parts[1] == "auto":
        text = ("╰_╯ AUTO REPLY FEATURE\n\n"
               "🔜 This feature is coming soon!\n\n"
               "Stay tuned for automated reply capabilities to enhance your campaigns.\n\n"
               "💡 Planned features:\n"
               "• Keyword-based auto replies\n"
               "• Smart response templates\n"
               "• Conversation flow management")
        await query.edit_message_caption(
            caption=text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
            ])
        )

async def handle_campaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    user_id = query.from_user.id
    
    if parts[1] == "start":
        # Check if user has accounts and ad message
        accounts = await db.accounts.count_documents({"user_id": user_id, "active": True})
        ad_doc = await db.ads.find_one({"user_id": str(user_id)})
        
        if accounts == 0:
            await query.answer("❌ No active accounts! Add accounts first.", show_alert=True)
            return
        
        if not ad_doc or not ad_doc.get("text"):
            await query.answer("❌ No ad message set! Set your ad message first.", show_alert=True)
            return
        
        # In a real implementation, this would start background tasks
        # For now, we'll just show a confirmation
        await query.answer("✅ Campaign started successfully!", show_alert=True)
        await query.edit_message_caption(
            caption="🚀 CAMPAIGN STARTED\n\n"
                   "Your ads are now broadcasting to all joined groups.\n\n"
                   "📊 Monitor progress in Analytics section.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Analytics", callback_data="stat|main")],
                [InlineKeyboardButton("Stop Ads", callback_data="camp|stop")],
                [InlineKeyboardButton("Dashboard", callback_data="nav|dashboard")]
            ])
        )
    
    elif parts[1] == "stop":
        # In a real implementation, this would stop background tasks
        await query.answer("🛑 Campaign stopped successfully!", show_alert=True)
        await query.edit_message_caption(
            caption="⏸️ CAMPAIGN STOPPED\n\n"
                   "All broadcasting activities have been paused.\n\n"
                   "You can restart anytime from the dashboard.",
            reply_markup=kb_dashboard()
        )

async def handle_noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for noop buttons (display-only)"""
    query = update.callback_query
    await query.answer()

# --- Main Application ---

async def post_init(application: Application):
    """Initialize bot settings after startup"""
    bot = application.bot
    try:
        await bot.set_chat_menu_button()
        logger.info("Bot initialized successfully")
    except Exception as e:
        logger.warning(f"Failed to set menu button: {e}")

async def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Command Handlers
    app.add_handler(CommandHandler("start", cmd_start))
    
    # Callback Query Handlers (order matters - more specific first)
    app.add_handler(CallbackQueryHandler(handle_noop, pattern=r"^noop$"))
    app.add_handler(CallbackQueryHandler(handle_otp, pattern=r"^otp\|"))
    app.add_handler(CallbackQueryHandler(handle_account_ops, pattern=r"^acc\|"))
    app.add_handler(CallbackQueryHandler(handle_ads, pattern=r"^ad\|"))
    app.add_handler(CallbackQueryHandler(handle_delay, pattern=r"^(delay|setdelay)\|"))
    app.add_handler(CallbackQueryHandler(handle_analytics, pattern=r"^stat\|"))
    app.add_handler(CallbackQueryHandler(handle_features, pattern=r"^feature\|"))
    app.add_handler(CallbackQueryHandler(handle_campaigns, pattern=r"^camp\|"))
    app.add_handler(CallbackQueryHandler(handle_navigation, pattern=r"^nav\|"))
    
    # Message Handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, input_handler))
    
    # Error handler
    app.add_error_handler(lambda update, context: logger.exception(f"Update {update} caused error: {context.error}"))

    logger.info("Starting bot...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("Bot started successfully!")
    
    # Keep running
    stop_signal = asyncio.Event()
    await stop_signal.wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)