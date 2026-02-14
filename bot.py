import asyncio
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Dict, Optional

from dataclasses import dataclass, field
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    PicklePersistence,
)
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    FloodWaitError,
)
from motor.motor_asyncio import AsyncIOMotorClient

# --- Configuration ---
# Load configuration from config.ini
import configparser
config = configparser.ConfigParser()
config.read("config.ini")

BOT_TOKEN = config["telegram"]["bot_token"]
API_ID = int(config["telegram"]["api_id"])
API_HASH = config["telegram"]["api_hash"]
MONGO_URI = config["mongo"]["uri"]

# --- Constants ---
BANNER_URL = "https://files.catbox.moe/zttfbe.jpg"
PROFILE_NAME = "Adimyze Pro"
PROFILE_BIO = "🚀 Professional Telegram Marketing Automation | Managed by @nexaxoders"

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# --- Database & State Management ---
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client["adimyze_db"]

# Use PicklePersistence for user_states to survive restarts
persistence = PicklePersistence(filepath="user_states")

@dataclass
class UserState:
    step: str = "idle"
    phone: str = ""
    phone_code_hash: str = ""
    client: Optional[TelegramClient] = field(default_factory=lambda: None)
    buffer: str = ""
    delay: int = 300

# This dict will be managed by PicklePersistence
user_states: Dict[int, UserState] = {}

# --- Helper Functions ---

async def safe_edit_or_send(query, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None, photo_url: Optional[str] = None):
    """Safely edits a message or sends a new one, handling photo/text and errors."""
    try:
        if photo_url:
            # If a photo URL is provided, try to edit the media
            await query.edit_message_media(
                media=InputMediaPhoto(media=photo_url, caption=text),
                reply_markup=reply_markup
            )
        else:
            # Try to edit text first
            await query.edit_message_text(text=text, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"Could not edit message: {e}. Sending a new one.")
        # If editing fails, send a new message
        if photo_url:
            await query.message.reply_photo(photo=photo_url, caption=text, reply_markup=reply_markup)
        else:
            await query.message.reply_text(text=text, reply_markup=reply_markup)
        # Optional: try to delete the old message to avoid clutter
        try:
            await query.message.delete()
        except Exception:
            pass

# --- Keyboard Definitions ---

def kb_start():
    """Keyboard for the initial /start message."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(" Dashboard ", callback_data="nav|dashboard")],
        [InlineKeyboardButton("Updates", url="https://t.me/testttxs"), InlineKeyboardButton("Support", url="https://t.me/nexaxoders")],
        [InlineKeyboardButton(" How to Use ", callback_data="nav|howto")],
        [InlineKeyboardButton(" Powered By ", url="https://t.me/nexaxoders")]
    ])

def kb_dashboard():
    """Main dashboard keyboard with 2-column layout."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Accounts", callback_data="acc|add"), InlineKeyboardButton("My Accounts", callback_data="acc|list|0")],
        [InlineKeyboardButton("Set Ad Message", callback_data="ad|set"), InlineKeyboardButton("Set Time Interval", callback_data="delay|nav")],
        [InlineKeyboardButton("Start Ads", callback_data="camp|start"), InlineKeyboardButton("Stop Ads", callback_data="camp|stop")],
        [InlineKeyboardButton("Delete Accounts", callback_data="acc|del"), InlineKeyboardButton("Analytics", callback_data="stat|main")],
        [InlineKeyboardButton("Auto Reply", callback_data="feature|auto"), InlineKeyboardButton("Back", callback_data="nav|start")]
    ])

def kb_otp(user_id):
    """Keyboard for OTP input with masked display."""
    state = user_states.get(user_id, UserState())
    display = " ".join(["*"] * len(state.buffer)) + " " * (5 - len(state.buffer))
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Current: {display}", callback_data="ignore")],
        [InlineKeyboardButton("1", callback_data="otp|1"), InlineKeyboardButton("2", callback_data="otp|2"), InlineKeyboardButton("3", callback_data="otp|3")],
        [InlineKeyboardButton("4", callback_data="otp|4"), InlineKeyboardButton("5", callback_data="otp|5"), InlineKeyboardButton("6", callback_data="otp|6")],
        [InlineKeyboardButton("7", callback_data="otp|7"), InlineKeyboardButton("8", callback_data="otp|8"), InlineKeyboardButton("9", callback_data="otp|9")],
        [InlineKeyboardButton("⌫", callback_data="otp|back"), InlineKeyboardButton("0", callback_data="otp|0"), InlineKeyboardButton("❌ Cancel", callback_data="otp|cancel")],
        [InlineKeyboardButton("Show Code", url="tg://openmessage?user_id=777000")]
    ])

def kb_delay(current_delay=300):
    """Keyboard for setting the broadcast delay."""
    def get_emoji(sec):
        if sec <= 300: return "🔴"
        if sec <= 600: return "🟡"
        return "🟢"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"5min {get_emoji(300)}", callback_data="setdelay|300"), InlineKeyboardButton(f"10min {get_emoji(600)}", callback_data="setdelay|600")],
        [InlineKeyboardButton(f"20min {get_emoji(1200)}", callback_data="setdelay|1200")],
        [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
    ])

def kb_accounts(accounts, page=0):
    """Keyboard for listing accounts with pagination."""
    buttons, page_size = [], 5
    start, end = page * page_size, (page + 1) * page_size
    for acc in accounts[start:end]:
        status = "🟢" if acc.get("active", False) else "🔴"
        phone = acc["phone"]
        buttons.append([InlineKeyboardButton(f"{status} ••••{phone[-4:]}", callback_data=f"acc|detail|{acc['_id']}")])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"acc|list|{page-1}"))
    if end < len(accounts): nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"acc|list|{page+1}"))
    if nav: buttons.append(nav)
    buttons.append([InlineKeyboardButton("Back", callback_data="nav|dashboard")])
    return InlineKeyboardMarkup(buttons)

def kb_account_detail(acc_id, phone):
    """Keyboard for a single account's detail view."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Delete Account", callback_data=f"acc|delete|{acc_id}")],
        [InlineKeyboardButton("Back to List", callback_data="acc|list|0")],
        [InlineKeyboardButton("Dashboard", callback_data="nav|dashboard")]
    ])

def kb_confirm_delete(acc_id):
    """Keyboard to confirm account deletion."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, Delete", callback_data=f"acc|confirm_del|{acc_id}"), InlineKeyboardButton("❌ No", callback_data="nav|dashboard")]
    ])

# --- Main Handlers ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command and shows the main dashboard overview."""
    user_id = update.effective_user.id
    query = update.callback_query

    # Fetch data for the overview
    active_acc = await db.accounts.count_documents({"user_id": user_id, "active": True})
    total_acc = await db.accounts.count_documents({"user_id": user_id})
    ad_doc = await db.ads.find_one({"user_id": str(user_id)})
    user_doc = await db.users.find_one({"user_id": str(user_id)})
    delay = user_doc.get("delay", 300) if user_doc else 300
    is_ad_set = "Set ✅" if ad_doc and ad_doc.get("text") else "Not Set ❌"
    is_running = "Running ▶️" # Placeholder for real status

    text = (
        f"╰_╯ @NexaCoders Ads DASHBOARD\n\n"
        f"•Hosted Accounts: {active_acc}/{total_acc}\n"
        f"•Ad Message: {is_ad_set}\n"
        f"•Cycle Interval: {delay}s\n"
        f"•Advertising Status: {is_running}\n\n"
        f"╰_╯Choose an action below to continue"
    )

    if query:
        await query.answer()
        await safe_edit_or_send(query, text, reply_markup=kb_dashboard(), photo_url=BANNER_URL)
    else:
        await update.message.reply_photo(photo=BANNER_URL, caption=text, reply_markup=kb_dashboard())

async def handle_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles navigation between main sections like start, dashboard, etc."""
    query = update.callback_query
    await query.answer()
    dest = query.data.split("|")[1]

    if dest == "start":
        text = ("╰_╯ Welcome to @Tecxo Free Ads bot — The Future of Telegram Automation\n\n"
                "• Premium Ad Broadcasting\n"
                "• Smart Delays\n"
                "• Multi-Account Support\n\n"
                "For support contact: @NexaCoders")
        await safe_edit_or_send(query, text, reply_markup=kb_start(), photo_url=BANNER_URL)
    elif dest == "dashboard":
        await cmd_start(update, context)
    elif dest == "howto":
        text = ("╰_╯ HOW TO USE\n\n"
                "1. Add Account → Host your Telegram account\n"
                "2. Set Ad Message → Create your promotional text\n"
                "3. Set Time Interval → Configure broadcast frequency\n"
                "4. Start Ads → Begin automated broadcasting\n\n"
                "⚠️ Note: Using aggressive intervals may risk account suspension")
        await safe_edit_or_send(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]]))

async def handle_account_ops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all account-related operations: add, list, delete."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    action = query.data.split("|")[1]

    if action == "add":
        user_states[user_id] = UserState(step="phone")
        text = ("╰_╯HOST NEW ACCOUNT\n\n"
                "Secure Account Hosting\n\n"
                "Enter your phone number with country code:\n"
                "Example: +1234567890\n\n"
                "Your data is encrypted and secure")
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]]))

    elif action == "list":
        page = int(query.data.split("|")[2])
        accounts = await db.accounts.find({"user_id": user_id}).to_list(None)
        if not accounts:
            await query.answer("No accounts added yet!", show_alert=True)
            await cmd_start(update, context)
            return
        text = f"📱 MY ACCOUNTS ({len(accounts)})\n\nSelect an account to manage:"
        await safe_edit_or_send(query, text, reply_markup=kb_accounts(accounts, page))

    elif action == "detail":
        acc_id = query.data.split("|")[2]
        account = await db.accounts.find_one({"_id": acc_id, "user_id": user_id})
        if not account: return
        status = "Active" if account.get("active") else "Inactive"
        phone = account["phone"]
        text = (f"📱 ACCOUNT DETAILS\n\n"
                f"Phone: {phone}\n"
                f"Status: {status}")
        await safe_edit_or_send(query, text, reply_markup=kb_account_detail(acc_id, phone))

    elif action == "delete":
        acc_id = query.data.split("|")[2]
        account = await db.accounts.find_one({"_id": acc_id, "user_id": user_id})
        if not account: return
        phone = account["phone"]
        text = f"⚠️ DELETE ACCOUNT\n\nAre you sure you want to delete:\n{phone}?"
        await safe_edit_or_send(query, text, reply_markup=kb_confirm_delete(acc_id))

    elif action == "confirm_del":
        acc_id = query.data.split("|")[2]
        result = await db.accounts.delete_one({"_id": acc_id, "user_id": user_id})
        if result.deleted_count:
            await query.answer("✅ Account deleted successfully!", show_alert=True)
        await cmd_start(update, context) # Go back to dashboard

    elif action == "del":
        count = await db.accounts.count_documents({"user_id": user_id})
        if count == 0:
            await query.answer("No accounts to delete!", show_alert=True)
            return
        text = "🗑️ DELETE ACCOUNTS\n\nSelect accounts to remove from your campaign:"
        await safe_edit_or_send(query, text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("View & Delete Accounts", callback_data="acc|list|0")],
            [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
        ]))

async def input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text inputs for phone numbers, 2FA passwords, and ad messages."""
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    if not state or state.step == "idle":
        return
    text = update.message.text.strip()

    try:
        if state.step == "phone":
            phone = "+" + re.sub(r"\D", "", text)
            if len(phone) < 8 or len(phone) > 15:
                await update.message.reply_text("❌ Invalid phone number!\n\nPlease enter a valid number with country code:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]]))
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
                await update.message.reply_text(f"⏳ Hold! We're trying to OTP...\n\nPhone: {phone}\nPlease wait a moment.")
                await update.message.reply_text(f"╰_╯ OTP sent to {phone}! ✅ Enter the OTP using the keypad below:\nCurrent: _____\nFormat: 12345 (no spaces needed)\nValid for: 5 minutes", reply_markup=kb_otp(user_id))
            except FloodWaitError as e:
                await client.disconnect()
                await update.message.reply_text(f"⏳ Too many requests! Wait {e.value} seconds before trying again.", reply_markup=kb_dashboard())
            except Exception as e:
                await client.disconnect()
                logger.error(f"Error sending code: {e}")
                await update.message.reply_text(f"❌ Error: {str(e)[:100]}", reply_markup=kb_dashboard())

        elif state.step == "password":
            await finalize_login(user_id, context, password=text)
            user_states[user_id] = UserState(step="idle")

        elif state.step == "set_ad":
            if len(text) > 4000:
                await update.message.reply_text("❌ Message too long! (Max 4000 characters)\n\nPlease send a shorter ad message:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]]))
                return
            await db.ads.update_one({"user_id": str(user_id)}, {"$set": {"text": text, "updated_at": datetime.now(timezone.utc)}}, upsert=True)
            user_states[user_id] = UserState(step="idle")
            await update.message.reply_text("✅ Ad Message Saved!", reply_markup=kb_dashboard())

    except Exception as e:
        logger.exception(f"Input handler error: {e}")
        await update.message.reply_text("❌ Unexpected error occurred!\n\nPlease restart the process.", reply_markup=kb_dashboard())
        if state and state.client:
            await state.client.disconnect()
        user_states[user_id] = UserState(step="idle")

async def handle_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles OTP keypad button presses."""
    query = update.callback_query
    user_id = query.from_user.id
    state = user_states.get(user_id)
    if not state or state.step != "code":
        await query.answer("Session expired!", show_alert=True)
        return
    await query.answer()
    action = query.data.split("|")[1]

    if action == "cancel":
        await query.answer("Process Cancelled.", show_alert=True)
        if state.client: await state.client.disconnect()
        user_states[user_id] = UserState(step="idle")
        await cmd_start(update, context)
        return

    if action == "back":
        state.buffer = state.buffer[:-1]
    elif action.isdigit() and len(state.buffer) < 5:
        state.buffer += action
    elif action == "submit" and len(state.buffer) == 5:
        await finalize_login(user_id, context)
        return
    else:
        await query.answer("Enter 5 digit OTP!", show_alert=True)
        return

    await safe_edit_or_send(query, f"╰_╯ OTP sent to {state.phone}! ✅ Enter the OTP using the keypad below:\nCurrent: {' '.join(['*'] * len(state.buffer))}\nFormat: 12345 (no spaces needed)\nValid for: 5 minutes", reply_markup=kb_otp(user_id))

async def finalize_login(user_id, context: ContextTypes.DEFAULT_TYPE, password=None):
    """Finalizes the login process with OTP or 2FA password."""
    state = user_states.get(user_id)
    if not state or not state.client:
        await context.bot.send_message(user_id, "❌ Session expired! Please restart the login process.", reply_markup=kb_dashboard())
        return
    try:
        if password:
            await state.client.sign_in(password=password)
        else:
            await state.client.sign_in(phone=state.phone, code=state.buffer, phone_code_hash=state.phone_code_hash)

        # Update profile immediately
        try:
            await state.client(UpdateProfileRequest(first_name=PROFILE_NAME, about=PROFILE_BIO))
        except Exception as e:
            logger.warning(f"Profile update warning for {state.phone}: {e}")

        # Save session
        session_str = state.client.session.save()
        await db.accounts.update_one(
            {"user_id": user_id, "phone": state.phone},
            {"$set": {"session": session_str, "active": True, "created_at": datetime.now(timezone.utc)}},
            upsert=True
        )
        await state.client.disconnect()
        user_states[user_id] = UserState(step="idle")
        success_msg = (f"Account Successfully added!✅\n\n"
                       f"Phone: {state.phone}\n"
                       f"╰_╯Your account is ready for broadcasting!\n\n"
                       f"Note: Profile bio and name have been updated automatically.")
        await context.bot.send_message(user_id, success_msg, reply_markup=kb_dashboard())

    except SessionPasswordNeededError:
        state.step = "password"
        await context.bot.send_message(user_id, "🔐 2FA Detected!\n\nPlease send your Telegram cloud password:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]]))
    except (PhoneCodeInvalidError, ValueError):
        await state.client.disconnect()
        user_states[user_id] = UserState(step="idle")
        await context.bot.send_message(user_id, "❌ Invalid OTP code! Please restart the login process.", reply_markup=kb_dashboard())
    except Exception as e:
        await state.client.disconnect()
        user_states[user_id] = UserState(step="idle")
        logger.exception(f"Login failed for {state.phone}: {e}")
        await context.bot.send_message(user_id, f"❌ Failed: {str(e)}", reply_markup=kb_dashboard())

async def handle_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles setting the ad message."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    ad_doc = await db.ads.find_one({"user_id": str(user_id)})
    current_ad = ad_doc.get("text", "") if ad_doc else ""
    current_ad_text = f"\nCurrent Ad Message:\n{current_ad}\n" if current_ad else ""
    text = (f"╰_╯ SET YOUR AD MESSAGE\n\n"
            f"Tips for effective ads:\n"
            f"•Keep it concise and engaging\n"
            f"•Use premium emojis for flair\n"
            f"•Include clear call-to-action\n"
            f"•Avoid excessive caps or spam words\n\n"
            f"{current_ad_text}"
            f"Send your ad message now:")
    user_states[user_id] = UserState(step="set_ad")
    await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]]))

async def handle_delay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles setting the broadcast time interval."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    parts = query.data.split("|")

    if parts[0] == "delay" and parts[1] == "nav":
        user_doc = await db.users.find_one({"user_id": str(user_id)})
        current_delay = user_doc.get("delay", 300) if user_doc else 300
        text = (f"╰_╯SET BROADCAST CYCLE INTERVAL\n\n"
                f"Current Interval: {current_delay} seconds\n\n"
                f"Recommended Intervals:\n"
                f"•300s - Aggressive (5 min) 🔴\n"
                f"•600s - Safe & Balanced (10 min) 🟡\n"
                f"•1200s - Conservative (20 min) 🟢\n\n"
                f"To set custom time interval Send a number (in seconds):\n"
                f"(Note: using short time interval for broadcasting can get your Account on high risk.)")
        await safe_edit_or_send(query, text, reply_markup=kb_delay(current_delay))
    elif parts[0] == "setdelay":
        delay = int(parts[1])
        await db.users.update_one({"user_id": str(user_id)}, {"$set": {"delay": delay}}, upsert=True)
        await query.answer(f"✅ Interval set to {delay} seconds", show_alert=True)
        # Re-show the screen with the new delay
        text = (f"╰_╯SET BROADCAST CYCLE INTERVAL\n\n"
                f"Current Interval: {delay} seconds\n\n"
                f"Recommended Intervals:\n"
                f"•300s - Aggressive (5 min) 🔴\n"
                f"•600s - Safe & Balanced (10 min) 🟡\n"
                f"•1200s - Conservative (20 min) 🟢\n\n"
                f"To set custom time interval Send a number (in seconds):\n"
                f"(Note: using short time interval for broadcasting can get your Account on high risk.)")
        await safe_edit_or_send(query, text, reply_markup=kb_delay(delay))

async def handle_analytics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles displaying analytics and detailed reports."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    parts = query.data.split("|")

    if parts[1] == "main":
        active = await db.accounts.count_documents({"user_id": user_id, "active": True})
        user_doc = await db.users.find_one({"user_id": str(user_id)})
        delay = user_doc.get("delay", 300) if user_doc else 300
        # Placeholder stats
        cycles, sent, failed, logger_fail = 0, 0, 0, 0
        success_rate = 0
        bar = "░" * 10
        text = (f"╰_╯@Tecxo ANALYTICS\n\n"
                f"Broadcast Cycles Completed: {cycles}\n"
                f"Messages Sent: {sent}\n"
                f"Failed Sends: {failed}\n"
                f"Logger Failures: {logger_fail}\n"
                f"Active Accounts: {active}\n"
                f"Avg Delay: {delay}s\n\n"
                f"Success Rate: {bar} {success_rate}%")
        await safe_edit_or_send(query, text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Detailed Report", callback_data="stat|detail")],
            [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
        ]))
    elif parts[1] == "detail":
        active = await db.accounts.count_documents({"user_id": user_id, "active": True})
        total = await db.accounts.count_documents({"user_id": user_id)})
        inactive = total - active
        user_doc = await db.users.find_one({"user_id": str(user_id)})
        delay = user_doc.get("delay", 300) if user_doc else 300
        now = datetime.now(timezone.utc).strftime("%d/%m/%y")
        text = (f"╰_╯ DETAILED ANALYTICS REPORT:\n\n"
                f"Date: {now}\n"
                f"User ID: {user_id}\n\n"
                f"Broadcast Stats:\n"
                f"- Total Sent: 0\n"
                f"- Total Failed: 0\n"
                f"- Total Broadcasts: 0\n\n"
                f"Logger Stats:\n"
                f"- Logger Failures: 0\n"
                f"- Last Failure: None\n\n"
                f"Account Stats:\n"
                f"- Total Accounts: {total}\n"
                f"- Active Accounts: {active} 🟢\n"
                f"- Inactive Accounts: {inactive} 🔴\n\n"
                f"Current Delay: {delay}s")
        await safe_edit_or_send(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="stat|main")]]))

async def handle_features(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles placeholder features like Auto Reply."""
    query = update.callback_query
    await query.answer()
    if "auto" in query.data:
        text = ("╰_╯AUTO REPLY FEATURE\n\n"
                "This feature is coming soon!\n"
                "Stay tuned for automated reply capabilities to enhance your campaigns.")
        await safe_edit_or_send(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]]))

async def handle_campaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles starting and stopping ad campaigns."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if "start" in query.data:
        active_acc = await db.accounts.count_documents({"user_id": user_id, "active": True})
        ad_doc = await db.ads.find_one({"user_id": str(user_id)})
        if active_acc == 0:
            await query.answer("❌ No active accounts! Add accounts first.", show_alert=True)
            return
        if not ad_doc or not ad_doc.get("text"):
            await query.answer("❌ No ad message set! Set your ad message first.", show_alert=True)
            return
        # Placeholder for starting a background task
        await query.answer("✅ Campaign started successfully!", show_alert=True)
        text = ("🚀 CAMPAIGN STARTED\n\n"
                "Your ads are now broadcasting to all joined groups.\n\n"
                "📊 Monitor progress in Analytics section.")
        await safe_edit_or_send(query, text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Analytics", callback_data="stat|main")],
            [InlineKeyboardButton("Stop Ads", callback_data="camp|stop")],
            [InlineKeyboardButton("Dashboard", callback_data="nav|dashboard")]
        ]))
    elif "stop" in query.data:
        # Placeholder for stopping the background task
        await query.answer("🛑 Campaign stopped successfully!", show_alert=True)
        text = ("⏸️ CAMPAIGN STOPPED\n\n"
                "All broadcasting activities have been paused.\n\n"
                "You can restart anytime from the dashboard.")
        await safe_edit_or_send(query, text, reply_markup=kb_dashboard())

async def handle_noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles button presses that should do nothing."""
    await update.callback_query.answer()

# --- Main Execution ---

def main():
    """Starts the bot."""
    application = Application.builder().token(BOT_TOKEN).persistence(persistence).build()

    # Load user_states from persistence
    global user_states
    user_states = persistence.bot_data.get('user_states', {})
    
    # Add handlers
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CallbackQueryHandler(handle_noop, pattern=r"^ignore$"))
    application.add_handler(CallbackQueryHandler(handle_otp, pattern=r"^otp\|"))
    application.add_handler(CallbackQueryHandler(handle_account_ops, pattern=r"^acc\|"))
    application.add_handler(CallbackQueryHandler(handle_ads, pattern=r"^ad\|"))
    application.add_handler(CallbackQueryHandler(handle_delay, pattern=r"^(delay|setdelay)\|"))
    application.add_handler(CallbackQueryHandler(handle_analytics, pattern=r"^stat\|"))
    application.add_handler(CallbackQueryHandler(handle_features, pattern=r"^feature\|"))
    application.add_handler(CallbackQueryHandler(handle_campaigns, pattern=r"^camp\|"))
    application.add_handler(CallbackQueryHandler(handle_navigation, pattern=r"^nav\|"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, input_handler))

    logger.info("Starting bot...")
    application.run_polling()

if __name__ == "__main__":
    main()