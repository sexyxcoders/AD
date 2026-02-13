import asyncio
import logging
import re
import sys
import os
import random
from datetime import datetime, timezone
from typing import Dict, Optional
from dataclasses import dataclass, field
from pathlib import Path

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

# ───────────── CONFIGURATION ─────────────
BOT_TOKEN = '8463982454:AAErd8EZswKgQ1BNF_r-N8iUH8HQcb293lQ'
API_ID = 22657083
API_HASH = 'd6186691704bd901bdab275ceaab88f3'
MONGO_URI = "mongodb+srv://bot627668:2bEJ56yJSu7vzLws@cluster0.qbw5van.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
DB_NAME = "adimyze"

SUDO_USERS = [2083251445]
PROFILE_NAME = "Adimyze Pro"
PROFILE_BIO = "🚀 Professional Telegram Marketing Automation | Managed by @nexaxoders"
SUPPORT_LINK = "https://t.me/nexaxoders"
UPDATE_CHANNEL = "https://t.me/testttxs"

logging.basicConfig(
    format='%(asctime)s | %(levelname)s | %(message)s', level=logging.INFO,
    handlers=[logging.FileHandler("adimyze.log"), logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DB_NAME]
PID_FILE = Path("/tmp/adimyze_pro_v19.pid")

# ───────────── USER STATE ─────────────
@dataclass
class UserState:
    step: str = "idle"  # idle, phone, code, password, set_min_delay, set_max_delay
    phone: str = ""
    phone_code_hash: str = ""
    client: Optional[TelegramClient] = None
    buffer: str = ""
    delay_min: int = 60
    delay_max: int = 180

    def reset(self):
        self.step = "idle"
        self.phone = ""
        self.buffer = ""
        if self.client:
            asyncio.create_task(self.client.disconnect())
        self.client = None

user_states: Dict[int, UserState] = {}
ad_tasks: Dict[int, asyncio.Task] = {}

# ───────────── KEYBOARDS ─────────────
def kb_dashboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Accounts", callback_data="nav|accounts"),
         InlineKeyboardButton("🎯 Ads", callback_data="nav|ads")],
        [InlineKeyboardButton("🚀 Start Ads", callback_data="campaign|start"),
         InlineKeyboardButton("🛑 Stop Ads", callback_data="campaign|stop")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="nav|settings"),
         InlineKeyboardButton("👤 My Stats", callback_data="nav|stats")],
        [InlineKeyboardButton("🆘 Help", url=SUPPORT_LINK),
         InlineKeyboardButton("📢 Updates", url=UPDATE_CHANNEL)]
    ])

def kb_accounts() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Account", callback_data="account|add")],
        [InlineKeyboardButton("🗑️ Delete Account", callback_data="account|delete")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav|home")]
    ])

def kb_ads() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh Ad", callback_data="ad|refresh")],
        [InlineKeyboardButton("🗑️ Delete Ad", callback_data="ad|delete")],
        [InlineKeyboardButton("🧹 Delete All Ads", callback_data="ad|delete_all")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav|home")]
    ])

def kb_settings(user_id: int) -> InlineKeyboardMarkup:
    state = user_states.get(user_id)
    min_d = state.delay_min if state else 60
    max_d = state.delay_max if state else 180
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⏱️ Min Delay: {min_d}s", callback_data="delay|min")],
        [InlineKeyboardButton(f"⏱️ Max Delay: {max_d}s", callback_data="delay|max")],
        [InlineKeyboardButton("🔙 Back", callback_data="nav|home")]
    ])

def kb_otp(user_id: int) -> InlineKeyboardMarkup:
    state = user_states.get(user_id)
    if not state:
        return kb_dashboard(user_id)
    display = (state.buffer + "●" * (5 - len(state.buffer)))[:5]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(display, callback_data="noop")],
        [InlineKeyboardButton("1", callback_data="otp|1"), InlineKeyboardButton("2", callback_data="otp|2"), InlineKeyboardButton("3", callback_data="otp|3")],
        [InlineKeyboardButton("4", callback_data="otp|4"), InlineKeyboardButton("5", callback_data="otp|5"), InlineKeyboardButton("6", callback_data="otp|6")],
        [InlineKeyboardButton("7", callback_data="otp|7"), InlineKeyboardButton("8", callback_data="otp|8"), InlineKeyboardButton("9", callback_data="otp|9")],
        [InlineKeyboardButton("⌫", callback_data="otp|back"), InlineKeyboardButton("0", callback_data="otp|0"), InlineKeyboardButton("✅", callback_data="otp|submit")],
        [InlineKeyboardButton("❌ Cancel", callback_data="otp|cancel")]
    ])

# ───────────── TEMPLATES ─────────────
DASHBOARD_CAPTION = """
👑 <b>Adimyze Pro Dashboard</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━
<b>Your marketing command center.</b>

✨ Features:
• Auto-use latest Saved Message as ad  
• Multi-Account Broadcasting  
• Custom Delays (Min/Max)  
• Real-Time Stats  

🛡️ Safe • Compliant • Professional

👨‍💻 Developed by @nexaxoders
"""

async def send_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
    user_id = update.effective_user.id
    photo_url = "https://telegra.ph/file/8a7f7e5c1a3b4e9d8f0a1.jpg"
    try:
        if edit and update.callback_query:
            await update.callback_query.edit_message_media(
                InputMediaPhoto(photo_url, caption=DASHBOARD_CAPTION, parse_mode=ParseMode.HTML),
                reply_markup=kb_dashboard(user_id)
            )
        else:
            await update.message.reply_photo(photo_url, caption=DASHBOARD_CAPTION, reply_markup=kb_dashboard(user_id), parse_mode=ParseMode.HTML)
    except Exception:
        text = DASHBOARD_CAPTION
        if edit and update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=kb_dashboard(user_id), parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(text, reply_markup=kb_dashboard(user_id), parse_mode=ParseMode.HTML)

async def fetch_latest_saved_message(client: TelegramClient):
    async for msg in client.iter_messages("me", limit=1):
        if msg.text or msg.media:
            return {"chat_id": "me", "msg_id": msg.id, "has_media": bool(msg.media)}
    return None

# ───────────── HANDLERS ─────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    if state:
        state.reset()
    await send_dashboard(update, context)

async def handle_nav(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    _, target = query.data.split("|", 1)

    if target == "home":
        await send_dashboard(update, context, edit=True)
    elif target == "accounts":
        await query.edit_message_text("📱 <b>Account Management</b>", reply_markup=kb_accounts(), parse_mode=ParseMode.HTML)
    elif target == "ads":
        ad_count = await db.ads.count_documents({"user_id": str(user_id)})
        status = f"✅ {ad_count} ads saved" if ad_count > 0 else "❌ No ad saved"
        await query.edit_message_text(f"🎯 <b>Ad Management</b>\n\nStatus: {status}", reply_markup=kb_ads(), parse_mode=ParseMode.HTML)
    elif target == "settings":
        await query.edit_message_text("⚙️ <b>Settings</b>", reply_markup=kb_settings(user_id), parse_mode=ParseMode.HTML)
    elif target == "stats":
        acc_count = await db.accounts.count_documents({"user_id": user_id})
        ad_count = await db.ads.count_documents({"user_id": str(user_id)})
        await query.edit_message_text(
            f"👤 <b>Your Stats</b>\n\n"
            f"📱 Accounts: {acc_count}\n"
            f"📢 Ads: {ad_count}\n"
            f"⚡ Campaign: {'🟢 Running' if user_id in ad_tasks else '🔴 Stopped'}",
            reply_markup=kb_dashboard(user_id),
            parse_mode=ParseMode.HTML
        )

async def handle_account_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    _, action = query.data.split("|", 1)

    if action == "add":
        user_states[user_id] = UserState(step="phone")
        await query.edit_message_text(
            "📲 Send your phone number in international format:\n<code>+1234567890</code>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="otp|cancel")]]),
            parse_mode=ParseMode.HTML
        )
    else:
        await query.edit_message_text("🗑️ Account deletion coming soon...", reply_markup=kb_accounts())

async def handle_ad_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    _, action = query.data.split("|", 1)

    if action == "refresh":
        accounts = await db.accounts.find({"user_id": user_id, "active": True}).to_list(None)
        if not accounts:
            await query.answer("❌ No active accounts!", show_alert=True)
            return

        session = accounts[0]["session"]
        client = TelegramClient(StringSession(session), API_ID, API_HASH)
        try:
            await client.connect()
            ad_data = await fetch_latest_saved_message(client)
            await client.disconnect()

            if ad_data:
                await db.ads.update_one(
                    {"user_id": str(user_id)},
                    {"$set": {**ad_data, "updated_at": datetime.now(timezone.utc)}},
                    upsert=True
                )
                await query.answer("✅ Ad refreshed from Saved Messages!", show_alert=True)
            else:
                await query.answer("❌ No message found in Saved Messages!", show_alert=True)
        except Exception as e:
            logger.error(f"Ad refresh error: {e}")
            await query.answer("❌ Failed to fetch ad!", show_alert=True)

    elif action == "delete":
        result = await db.ads.delete_one({"user_id": str(user_id)})
        msg = "✅ Ad deleted." if result.deleted_count else "❌ No ad to delete."
        await query.answer(msg, show_alert=True)
        await handle_nav(update, context)

    elif action == "delete_all":
        result = await db.ads.delete_many({"user_id": str(user_id)})
        await query.answer(f"🧹 Deleted {result.deleted_count} ads.", show_alert=True)
        await handle_nav(update, context)

async def handle_delay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    _, which = query.data.split("|", 1)

    state = user_states.setdefault(user_id, UserState())
    state.step = f"set_{which}_delay"
    current = state.delay_min if which == "min" else state.delay_max
    await query.edit_message_text(
        f"⏱️ Send new {which} delay (seconds):\nCurrent: {current}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="nav|settings")]])
    )

async def handle_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    if not state or state.step != "phone":
        return

    raw = re.sub(r"\D", "", update.message.text)
    if len(raw) < 10:
        await update.message.reply_text("❌ Invalid number.")
        return

    phone = "+" + raw
    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        sent = await client.send_code_request(phone)
        state.phone = phone
        state.client = client
        state.phone_code_hash = sent.phone_code_hash
        state.step = "code"

        await update.message.reply_text(
            f"🔑 Code sent to {phone[-10:]}. Use keypad:",
            reply_markup=kb_otp(user_id)
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        if state: state.reset()

async def handle_delay_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    if not state or "delay" not in state.step:
        return

    try:
        value = int(update.message.text.strip())
        if value < 10 or value > 3600:
            raise ValueError
        if state.step == "set_min_delay":
            state.delay_min = value
        else:
            state.delay_max = value
        await update.message.reply_text(f"✅ Delay updated to {value}s.", reply_markup=kb_settings(user_id))
        state.step = "idle"
    except ValueError:
        await update.message.reply_text("❌ Enter a number between 10–3600.")

async def handle_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    state = user_states.get(user_id)
    if not state or state.step != "code":
        await query.edit_message_text("⚠️ Expired. Use /start.", reply_markup=kb_dashboard(user_id))
        return

    _, action = query.data.split("|", 1)
    if action == "cancel":
        state.reset()
        await send_dashboard(update, context, edit=True)
        return
    elif action == "back":
        state.buffer = state.buffer[:-1]
    elif action.isdigit() and len(state.buffer) < 5:
        state.buffer += action
        if len(state.buffer) == 5:
            await finalize_login(user_id, query, state, context)
            return
    elif action == "submit":
        if len(state.buffer) != 5:
            await query.answer("❗ Enter all 5 digits!", show_alert=True)
            return
        await finalize_login(user_id, query, state, context)
        return

    display = (state.buffer + "●" * (5 - len(state.buffer)))[:5]
    await query.edit_message_text(f"🔑 Code sent to {state.phone[-10:]}:", reply_markup=kb_otp(user_id))

async def handle_password_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    if not state or state.step != "password":
        return

    password = update.message.text.strip()
    await update.message.reply_text("⏳ Verifying 2FA...")
    await finalize_login(user_id, None, state, context, password=password)

async def finalize_login(user_id: int, query, state: UserState, context, password: str = None):
    try:
        if query: await query.edit_message_text("⏳ Finalizing login...")

        if state.step == "code":
            await state.client.sign_in(phone=state.phone, code=state.buffer, phone_code_hash=state.phone_code_hash)
        elif password:
            await state.client.sign_in(password=password)
        else:
            raise Exception("No auth method")

        await state.client(UpdateProfileRequest(first_name=PROFILE_NAME, about=PROFILE_BIO))
        session_str = state.client.session.save()
        me = await state.client.get_me()

        await db.accounts.update_one(
            {"user_id": user_id, "phone": state.phone},
            {"$set": {
                "session": session_str, "username": me.username, "active": True, "last_used": datetime.now(timezone.utc)
            }},
            upsert=True
        )

        ad_data = await fetch_latest_saved_message(state.client)
        if ad_data:
            await db.ads.update_one(
                {"user_id": str(user_id)},
                {"$set": {**ad_data, "updated_at": datetime.now(timezone.utc)}},
                upsert=True
            )

        msg = f"✅ <b>Account added!</b>\nPhone: <code>{state.phone}</code>\nProfile updated and ad fetched."
        if query:
            await query.edit_message_text(msg, reply_markup=kb_dashboard(user_id), parse_mode=ParseMode.HTML)
        else:
            await context.bot.send_message(user_id, msg, reply_markup=kb_dashboard(user_id), parse_mode=ParseMode.HTML)
        state.reset()

    except SessionPasswordNeededError:
        state.step = "password"
        text = "🔐 This account has 2FA enabled. Please send your password in the chat:"
        if query: await query.edit_message_text(text)
        else: await context.bot.send_message(user_id, text)
    except Exception as e:
        logger.error(f"Login error: {e}")
        state.reset()

async def handle_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    _, action = query.data.split("|", 1)

    if action == "start":
        accounts = await db.accounts.find({"user_id": user_id, "active": True}).to_list(None)
        ad = await db.ads.find_one({"user_id": str(user_id)})
        if not accounts or not ad:
            await query.answer("❌ Missing active account or ad!", show_alert=True)
            return

        if user_id in ad_tasks: ad_tasks[user_id].cancel()
        ad_tasks[user_id] = asyncio.create_task(run_campaign(user_id, accounts, ad))
        await query.edit_message_text("🚀 <b>Campaign started!</b>", reply_markup=kb_dashboard(user_id), parse_mode=ParseMode.HTML)

    elif action == "stop":
        if user_id in ad_tasks:
            ad_tasks[user_id].cancel()
            del ad_tasks[user_id]
        await query.edit_message_text("🛑 <b>Campaign stopped.</b>", reply_markup=kb_dashboard(user_id), parse_mode=ParseMode.HTML)

async def run_campaign(user_id: int, accounts: list, ad: dict):
    while True:
        state = user_states.get(user_id, UserState())
        for acc in accounts:
            try:
                client = TelegramClient(StringSession(acc["session"]), API_ID, API_HASH)
                await client.connect()
                async for dialog in client.iter_dialogs():
                    if (dialog.is_group or dialog.is_channel) and not dialog.is_user:
                        try:
                            await client.forward_messages(dialog.id, ad["msg_id"], ad["chat_id"])
                            logger.info(f"User {user_id} sent to {dialog.name}")
                        except Exception: pass
                await client.disconnect()
            except Exception as e:
                logger.error(f"Campaign error: {e}")
        
        delay = random.randint(state.delay_min, state.delay_max)
        await asyncio.sleep(delay)

async def start_bot():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(handle_nav, pattern="^nav|"))
    app.add_handler(CallbackQueryHandler(handle_account_action, pattern="^account|"))
    app.add_handler(CallbackQueryHandler(handle_ad_action, pattern="^ad|"))
    app.add_handler(CallbackQueryHandler(handle_delay, pattern="^delay|"))
    app.add_handler(CallbackQueryHandler(handle_otp, pattern="^otp|"))
    app.add_handler(CallbackQueryHandler(handle_campaign, pattern="^campaign|"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r"^\+?\d+$"), handle_phone_input))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r"^\d+$"), handle_delay_input))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_password_input))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("✅ Adimyze Pro v19 is active!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        pass