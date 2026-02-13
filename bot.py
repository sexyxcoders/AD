import asyncio
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Dict, Optional
from dataclasses import dataclass, field

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
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
    PhoneNumberInvalidError,
    FloodWaitError,
)

from motor.motor_asyncio import AsyncIOMotorClient

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
ad_tasks: Dict[int, asyncio.Task] = {}

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
    state = user_states.get(user_id)
    if not state:
        return kb_dashboard()
    display = (state.buffer + "●" * (5 - len(state.buffer)))[:5]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(display, callback_data="noop")],
        [InlineKeyboardButton("1", callback_data="otp|1"),
         InlineKeyboardButton("2", callback_data="otp|2"),
         InlineKeyboardButton("3", callback_data="otp|3")],
        [InlineKeyboardButton("4", callback_data="otp|4"),         InlineKeyboardButton("5", callback_data="otp|5"),
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

WELCOME_TEXT = """╰_╯ Welcome to @Tecxo Free Ads bot — The Future of Telegram Automation 

• Premium Ad Broadcasting
• Smart Delays
• Multi-Account Support

For support contact: @NexaCoders"""

HOW_TO_USE = """╰_╯ HOW TO USE

1. Add your Telegram account(s)
2. Set your ad message
3. Configure broadcast interval
4. Start the campaign!
5. Monitor analytics

⚠️ Use dedicated accounts for best results."""

ADD_ACCOUNT_PROMPT = """╰_╯HOST NEW ACCOUNT

Secure Account Hosting

Enter your phone number with country code:
Example: +1234567890

Your data is encrypted and secure"""

OTP_WAIT = """⏳ Hold! We're trying to OTP...

Phone: {phone}
Please wait a moment."""

OTP_INPUT = """Open inline keyboard
To enter otp"""

TWO_FA_PROMPT = """🔐 2FA Detected!

Please send your Telegram cloud password:"""

LOGIN_SUCCESS = """Account Successfully added!✅

Phone: {phone}
╰_╯Your account is ready for broadcasting!
Note: Profile bio and name will be updated during the first broadcast, you change it if you want."""

SET_AD_PROMPT = """╰_╯ SET YOUR AD MESSAGE

Tips for effective ads:
• Keep it concise and engaging
• Use premium emojis for flair
• Include clear call-to-action
• Avoid excessive caps or spam words

Send your ad message now:"""

SET_DELAY_PROMPT = """╰_╯SET BROADCAST CYCLE INTERVAL

Current Interval: {current}s

Recommended Intervals:
• 300s - Aggressive (5 min) 🔴
• 600s - Safe & Balanced (10 min) 🟡
• 1200s - Conservative (20 min) 🟢

To set custom time interval Send a number (in seconds):

(Note: using short time interval for broadcasting can get your Account on high risk.)"""

ANALYTICS_SUMMARY = """╰_╯@NexaCoders ANALYTICS

Broadcast Cycles Completed: {cycles}
Messages Sent: {sent}
Failed Sends: {failed}Logger Failures: 0
Active Accounts: {active_acc}
Avg Delay: {delay}s

Success Rate: ▓▓▓▓▓▓▓▓▓▓ {rate}%"""

DETAILED_REPORT = """╰_╯ DETAILED ANALYTICS REPORT:

Date: {date}
User ID: {user_id}

Broadcast Stats:
- Total Sent: {sent}
- Total Failed: {failed}
- Total Broadcasts: {cycles}

Logger Stats:
- Logger Failures: 0
- Last Failure: None

Account Stats:
- Total Accounts: {total_acc}
- Active Accounts: {active_acc} 🟢
- Inactive Accounts: {inactive_acc} 🔴

Current Delay: {delay}s"""

AUTO_REPLY_MSG = """╰_╯AUTO REPLY FEATURE

This feature is coming soon!
Stay tuned for automated reply capabilities to enhance your campaigns."""

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_url = "https://telegra.ph/file/8a7f7e5c1a3b4e9d8f0a1.jpg"
    try:
        await update.message.reply_photo(photo_url, caption=WELCOME_TEXT, reply_markup=kb_start(), parse_mode=ParseMode.HTML)
    except BadRequest:
        await update.message.reply_text(WELCOME_TEXT, reply_markup=kb_start(), parse_mode=ParseMode.HTML)

async def handle_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, target = query.data.split("|", 1)

    if target == "start":
        await cmd_start(query, context)
    elif target == "dashboard":
        await query.edit_message_text("Dashboard:", reply_markup=kb_dashboard())
    elif target == "howto":
        await query.edit_message_text(HOW_TO_USE, reply_markup=kb_back("nav|start"))
async def handle_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, action = query.data.split("|", 1)
    user_id = query.from_user.id

    if action == "add":
        user_states[user_id] = UserState(step="phone")
        await query.edit_message_text(ADD_ACCOUNT_PROMPT, reply_markup=kb_back("nav|dashboard"))
    elif action == "list":
        accounts = await db.accounts.count_documents({"user_id": user_id})
        await query.edit_message_text(f"My Accounts: {accounts} total", reply_markup=kb_back("nav|dashboard"))
    elif action == "delete":
        await query.edit_message_text("Delete Accounts feature coming soon...", reply_markup=kb_back("nav|dashboard"))

async def handle_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_states[user_id] = UserState(step="set_ad")
    await query.edit_message_text(SET_AD_PROMPT, reply_markup=kb_back("nav|dashboard"))

async def handle_ad_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    if not state or state.step != "set_ad":
        return

    await db.ads.update_one(
        {"user_id": str(user_id)},
        {"$set": {
            "chat_id": update.message.chat_id,
            "msg_id": update.message.id,
            "text": update.message.text or "",
            "has_media": bool(update.message.media),
            "updated_at": datetime.now(timezone.utc)
        }},
        upsert=True
    )
    await update.message.reply_text("✅ Ad message saved!", reply_markup=kb_dashboard())
    state.step = "idle"

async def handle_delay_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    state = user_states.setdefault(user_id, UserState())
    await query.edit_message_text(SET_DELAY_PROMPT.format(current=state.delay), reply_markup=kb_delay_presets())
async def handle_delay_preset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, seconds = query.data.split("|", 1)
    user_id = query.from_user.id
    state = user_states.setdefault(user_id, UserState())
    state.delay = int(seconds)
    await query.edit_message_text(f"✅ Delay set to {seconds} seconds.", reply_markup=kb_back("nav|dashboard"))

async def handle_delay_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        delay = int(update.message.text.strip())
        if delay < 60 or delay > 3600:
            raise ValueError
        state = user_states.setdefault(user_id, UserState())
        state.delay = delay
        await update.message.reply_text(f"✅ Custom delay set to {delay} seconds.", reply_markup=kb_dashboard())
    except ValueError:
        await update.message.reply_text("❌ Enter a number between 60–3600.")

async def handle_analytics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, view = query.data.split("|", 1)
    user_id = query.from_user.id

    accounts = await db.accounts.count_documents({"user_id": user_id})
    active_acc = await db.accounts.count_documents({"user_id": user_id, "active": True})
    state = user_states.get(user_id) or UserState()

    if view == "main":
        sent = 0
        failed = 0
        cycles = 0
        rate = 0 if (sent + failed) == 0 else int((sent / (sent + failed)) * 100)

        await query.edit_message_text(
            ANALYTICS_SUMMARY.format(
                cycles=cycles,
                sent=sent,
                failed=failed,
                active_acc=active_acc,
                delay=state.delay,
                rate=rate
            ),
            reply_markup=kb_analytics_detailed()
        )
    elif view == "detailed":
        date = datetime.now().strftime("%d/%m/%y")        inactive_acc = accounts - active_acc
        await query.edit_message_text(
            DETAILED_REPORT.format(
                date=date,
                user_id=user_id,
                sent=0,
                failed=0,
                cycles=0,
                total_acc=accounts,
                active_acc=active_acc,
                inactive_acc=inactive_acc,
                delay=state.delay
            ),
            reply_markup=kb_back("analytics|main")
        )

async def handle_feature(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(AUTO_REPLY_MSG, reply_markup=kb_back("nav|dashboard"))

async def handle_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    if not state or state.step != "phone":
        return

    raw = re.sub(r"\D", "", update.message.text)
    if len(raw) < 10:
        await update.message.reply_text("❌ Invalid number.")
        return

    phone = "+" + raw if not raw.startswith("+") else raw
    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        sent = await client.send_code_request(phone)

        state.phone = phone
        state.client = client
        state.phone_code_hash = sent.phone_code_hash
        state.step = "code"

        await update.message.reply_text(OTP_WAIT.format(phone=phone))
        await update.message.reply_text(OTP_INPUT, reply_markup=kb_otp(user_id))
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        state.step = "idle"

async def handle_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    state = user_states.get(user_id)
    if not state or state.step != "code":
        await query.edit_message_text("⚠️ Expired.", reply_markup=kb_dashboard())
        return

    _, action = query.data.split("|", 1)
    if action == "back":
        state.buffer = state.buffer[:-1]
    elif action == "show":
        await query.answer(f"Code: {state.buffer}", show_alert=True)
        return
    elif action.isdigit() and len(state.buffer) < 5:
        state.buffer += action
        if len(state.buffer) == 5:
            await finalize_login(user_id, query, state)
            return
    elif action == "submit":
        if len(state.buffer) != 5:
            await query.answer("❗ Enter all 5 digits!", show_alert=True)
            return
        await finalize_login(user_id, query, state)
        return

    display = (state.buffer + "●" * (5 - len(state.buffer)))[:5]
    await query.edit_message_text("Open inline keyboard\nTo enter otp", reply_markup=kb_otp(user_id))

async def handle_password_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    if not state or state.step != "password":
        return

    await finalize_login(user_id, None, state, password=update.message.text.strip())

async def finalize_login(user_id: int, query, state: UserState, password: str = None):
    try:
        if query:
            await query.edit_message_text("⏳ Finalizing...")

        if state.step == "code":
            await state.client.sign_in(phone=state.phone, code=state.buffer, phone_code_hash=state.phone_code_hash)
        elif password:
            await state.client.sign_in(password=password)
        else:
            raise Exception("No auth")

        await state.client(UpdateProfileRequest(first_name=PROFILE_NAME, about=PROFILE_BIO))
        session_str = state.client.session.save()
        me = await state.client.get_me()

        await db.accounts.update_one(
            {"user_id": user_id, "phone": state.phone},
            {"$set": {
                "session": session_str,
                "username": me.username,
                "active": True,
                "last_used": datetime.now(timezone.utc)
            }},
            upsert=True
        )

        msg = LOGIN_SUCCESS.format(phone=state.phone)
        if query:
            await query.edit_message_text(msg, reply_markup=kb_dashboard())
        else:
            await context.bot.send_message(user_id, msg, reply_markup=kb_dashboard())
        state.step = "idle"

    except SessionPasswordNeededError:
        state.step = "password"
        text = TWO_FA_PROMPT
        if query:
            await query.edit_message_text(text, reply_markup=kb_back("nav|dashboard"))
        else:
            await context.bot.send_message(user_id, text, reply_markup=kb_back("nav|dashboard"))
    except (PhoneCodeInvalidError, ValueError):
        state.buffer = ""
        if query:
            await query.answer("❌ Invalid code!", show_alert=True)
            await query.edit_message_text("Open inline keyboard\nTo enter otp", reply_markup=kb_otp(user_id))
    except Exception as e:
        if query:
            await query.edit_message_text(f"❌ Login failed: {str(e)[:100]}", reply_markup=kb_dashboard())
        else:
            await context.bot.send_message(user_id, f"❌ Login failed: {str(e)[:100]}", reply_markup=kb_dashboard())
        state.step = "idle"

async def handle_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, action = query.data.split("|", 1)
    user_id = query.from_user.id

    if action == "start":
        accounts = await db.accounts.count_documents({"user_id": user_id, "active": True})
        ad = await db.ads.find_one({"user_id": str(user_id)})        if not accounts:
            await query.answer("❌ No accounts!", show_alert=True)
            return
        if not ad:
            await query.answer("❌ No ad message!", show_alert=True)
            return
        await query.edit_message_text("🚀 Ads started!", reply_markup=kb_dashboard())
    elif action == "stop":
        await query.edit_message_text("🛑 Ads stopped.", reply_markup=kb_dashboard())

async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(handle_nav, pattern=r"^nav\|"))
    app.add_handler(CallbackQueryHandler(handle_account, pattern=r"^account\|"))
    app.add_handler(CallbackQueryHandler(handle_ad, pattern=r"^ad\|"))
    app.add_handler(CallbackQueryHandler(handle_delay_nav, pattern=r"^delay\|set$"))
    app.add_handler(CallbackQueryHandler(handle_delay_preset, pattern=r"^delay\|(300|600|1200)$"))
    app.add_handler(CallbackQueryHandler(handle_analytics, pattern=r"^analytics\|"))
    app.add_handler(CallbackQueryHandler(handle_feature, pattern=r"^feature\|"))
    app.add_handler(CallbackQueryHandler(handle_otp, pattern=r"^otp\|"))
    app.add_handler(CallbackQueryHandler(handle_campaign, pattern=r"^campaign\|"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r"^\d+$"), handle_delay_custom))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone_input))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_password_input))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ad_input))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("✅ Bot is running!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")