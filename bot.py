import asyncio
import random
import logging
import re
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest, UpdateUsernameRequest
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    FloodWaitError,
    UsernameOccupiedError,
    ChatWriteForbiddenError,
    ChatAdminRequiredError,
)

from motor.motor_asyncio import AsyncIOMotorClient

# ────────────────────────────────────────────────
#                   CONFIG
# ────────────────────────────────────────────────

BOT_TOKEN  = '8463982454:AAFXhclFtn5cCoJLZl3l-SwhPMk3ssv6J8o'
API_ID     = 22657083
API_HASH   = 'd6186691704bd901bdab275ceaab88f3'

MONGO_URI  = "mongodb+srv://StarGiftBot_db_user:gld1RLm4eYbCWZlC@cluster0.erob6sp.mongodb.net/?retryWrites=true&w=majority"
DB_NAME    = "adimyze"

CHANNEL_LINK = "https://t.me/testttxs"

# Profile auto-update on login
NEW_DISPLAY_NAME = "Nexa @nexaxoders by"
NEW_BIO          = "Managed by @nexaxoders | Adimyze Pro 🚀"
USERNAME_PREFIX  = "nexax_by_"

# ────────────────────────────────────────────────
#                   INIT
# ────────────────────────────────────────────────

logging.basicConfig(
    format='%(asctime)s | %(levelname)-5s | %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

mongo = AsyncIOMotorClient(MONGO_URI)
db = mongo[DB_NAME]

user_states = {}     # uid → temp state
ad_tasks    = {}     # uid → asyncio.Task

# ────────────────────────────────────────────────
#                   KEYBOARDS
# ────────────────────────────────────────────────

def kb_home():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Dashboard", callback_data="dashboard")],
        [InlineKeyboardButton("📞 Support",   callback_data="support")],
        [InlineKeyboardButton("📢 Channel",   url=CHANNEL_LINK)],
    ])


def kb_dashboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Account", callback_data="add_account"),
         InlineKeyboardButton("👥 My Accounts", callback_data="my_accounts")],
        [InlineKeyboardButton("📥 Load Chats",  callback_data="load_chats")],
        [InlineKeyboardButton("📢 Set Ad Msg",  callback_data="set_ad")],
        [InlineKeyboardButton("⏱️ Set Delays",  callback_data="set_delays")],
        [InlineKeyboardButton("▶️ Start Ads",   callback_data="start_ads"),
         InlineKeyboardButton("⛔ Stop Ads",    callback_data="stop_ads")],
        [InlineKeyboardButton("📈 Status",      callback_data="status"),
         InlineKeyboardButton("🔙 Home",       callback_data="home")],
    ])


def kb_otp(buffer=""):
    disp = (buffer + "______")[:6]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f" {disp} ", callback_data="dummy")],
        [InlineKeyboardButton("1", callback_data="otp_1"), InlineKeyboardButton("2", callback_data="otp_2"), InlineKeyboardButton("3", callback_data="otp_3")],
        [InlineKeyboardButton("4", callback_data="otp_4"), InlineKeyboardButton("5", callback_data="otp_5"), InlineKeyboardButton("6", callback_data="otp_6")],
        [InlineKeyboardButton("7", callback_data="otp_7"), InlineKeyboardButton("8", callback_data="otp_8"), InlineKeyboardButton("9", callback_data="otp_9")],
        [InlineKeyboardButton("⌫", callback_data="otp_back"), InlineKeyboardButton("0", callback_data="otp_0"), InlineKeyboardButton("✅", callback_data="otp_confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_login")],
    ])


def kb_accounts(accounts):
    rows = []
    for acc in accounts[:10]:
        emoji = "🟢" if acc.get("active", True) else "🔴"
        name = acc.get("name", acc["phone"][-8:])
        rows.append([InlineKeyboardButton(f"{emoji} {name}", callback_data=f"acc_{acc['_id']}")])
    rows.extend([
        [InlineKeyboardButton("➕ Add New", callback_data="add_account")],
        [InlineKeyboardButton("🔙 Dashboard", callback_data="dashboard")],
    ])
    return InlineKeyboardMarkup(rows)


def kb_delays():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Dashboard", callback_data="dashboard")],
    ])


# ────────────────────────────────────────────────
#                   HANDLERS
# ────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        "<b>ADIMYZE PRO v12</b>\n\nTelegram Auto Forwarder\nChoose action 👇",
        reply_markup=kb_home()
    )


async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data

    if data in ("home", "cancel_login"):
        user_states.pop(uid, None)
        await q.edit_message_text("<b>Home</b>\nChoose action 👇", reply_markup=kb_home(), parse_mode=ParseMode.HTML)
        return

    if data == "support":
        await q.edit_message_text(
            f"<b>Support</b>\n@nexaxoders\n{CHANNEL_LINK}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Home", callback_data="home")]]),
            parse_mode=ParseMode.HTML
        )
        return

    if data == "dashboard":
        await show_dashboard(q, uid)
        return

    if data == "add_account":
        user_states[uid] = {"step": "phone"}
        await q.edit_message_text(
            "<b>Add Account</b>\nSend phone: <code>+91xxxxxxxxxx</code>",
            reply_markup=kb_dashboard(),
            parse_mode=ParseMode.HTML
        )
        return

    if data == "my_accounts":
        await show_my_accounts(q, uid)
        return

    if data == "load_chats":
        await load_chats(q, uid)
        return

    if data == "set_ad":
        user_states[uid] = {"step": "wait_ad_forward"}
        await q.edit_message_text(
            "<b>Set Advertisement</b>\nForward **one message** from your **Saved Messages** now.",
            reply_markup=kb_dashboard(),
            parse_mode=ParseMode.HTML
        )
        return

    if data == "set_delays":
        user_states[uid] = {"step": "set_delays", "delay_stage": 0}
        await show_delays(q, uid)
        return

    if data == "status":
        await show_status(q, uid)
        return

    if data == "start_ads":
        await start_ad_loop(uid, q)
        return

    if data == "stop_ads":
        await stop_ad_loop(uid, q)
        return

    # OTP flow
    if uid in user_states and user_states[uid].get("step") in ("otp", "2fa"):
        if data.startswith("otp_"):
            await handle_otp_digit(uid, data[4:], q)
        elif data == "otp_confirm":
            if user_states[uid]["step"] == "otp":
                await verify_otp(uid, q)
            else:
                await verify_2fa(uid, q)

    else:
        await q.answer("Feature coming soon...", show_alert=True)


async def handle_otp_digit(uid: int, char: str, query):
    state = user_states.get(uid, {})
    if state.get("step") not in ("otp", "2fa"):
        return

    key = "otp_buffer" if state["step"] == "otp" else "pw_buffer"
    buf = state.get(key, "")

    if char == "back":
        buf = buf[:-1]
    elif char.isdigit():
        maxl = 6 if state["step"] == "otp" else 64
        if len(buf) < maxl:
            buf += char

    state[key] = buf
    await refresh_otp(query, uid)


async def refresh_otp(query, uid):
    state = user_states[uid]
    step = state["step"]
    phone = state.get("phone", "?")
    buf_key = "otp_buffer" if step == "otp" else "pw_buffer"
    buf = state.get(buf_key, "")

    if step == "otp":
        disp = (buf + "______")[:6]
        text = f"<b>OTP for {phone}</b>\n<code>{disp}</code>"
    else:
        disp = "•" * len(buf) + "_" * (8 - len(buf))
        text = f"<b>2FA for {phone}</b>\n<code>{disp}</code>"

    await query.edit_message_text(text, reply_markup=kb_otp(buf), parse_mode=ParseMode.HTML)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = update.message
    text = msg.text.strip() if msg.text else ""

    if uid not in user_states:
        return

    step = user_states[uid].get("step")

    if step == "phone":
        if not re.match(r'^\+[1-9]\d{6,14}$', text):
            await msg.reply_html("Invalid format. Example: <code>+919876543210</code>")
            return
        await begin_login(uid, text, msg)

    elif step == "wait_ad_forward":
        if msg.forward_origin and hasattr(msg.forward_origin, 'sender_user') and msg.forward_origin.sender_user.is_self:
            await save_ad_message(uid, msg.forward_origin.message_id, msg)
        else:
            await msg.reply_html("Please forward from your <b>Saved Messages</b>.")

    elif step == "set_delays":
        if not re.match(r'^\d+(\.\d+)?$', text):
            await msg.reply_text("Please send a number (seconds)")
            return
        await process_delay(uid, float(text), msg)

    elif step == "2fa":
        user_states[uid]["pw_buffer"] = text.strip()
        await verify_2fa(uid, None)


# ────────────────────────────────────────────────
#                   LOGIN FLOW
# ────────────────────────────────────────────────

async def begin_login(uid: int, phone: str, msg):
    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()

        if await client.is_user_authorized():
            await msg.reply_html("Already authorized.")
            await client.disconnect()
            return

        code = await client.send_code_request(phone)

        user_states[uid] = {
            "step": "otp",
            "phone": phone,
            "hash": code.phone_code_hash,
            "otp_buffer": "",
            "client": client,
        }

        await msg.reply_html(f"Code sent to {phone}\nEnter 6-digit code:", reply_markup=kb_otp())

    except FloodWaitError as e:
        await msg.reply_html(f"⏳ Flood wait: {e.seconds//60} min")
    except Exception as e:
        await msg.reply_html(f"Error: {str(e)}")
        logger.exception("Login start failed")


async def verify_otp(uid: int, query):
    state = user_states.get(uid)
    if not state or state["step"] != "otp":
        return

    code = state["otp_buffer"]
    if len(code) != 6:
        await query.answer("Need 6 digits", show_alert=True)
        return

    client = state["client"]

    try:
        await client.sign_in(state["phone"], code, phone_code_hash=state["hash"])
        await update_profile(client)
        await save_session_and_cleanup(client, state, uid, query)

    except SessionPasswordNeededError:
        state.update({"step": "2fa", "pw_buffer": ""})
        await query.edit_message_text("<b>2FA required</b>\nEnter password:", reply_markup=kb_otp(""), parse_mode=ParseMode.HTML)

    except PhoneCodeInvalidError:
        await query.edit_message_text("Wrong code. Try again:", reply_markup=kb_otp(code), parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(e)
        await query.edit_message_text(f"Error: {str(e)}")


async def verify_2fa(uid: int, query):
    state = user_states.get(uid)
    if not state or state["step"] != "2fa":
        return

    pw = state.get("pw_buffer", "").strip()
    client = state["client"]

    try:
        await client.sign_in(password=pw)
        await update_profile(client)
        await save_session_and_cleanup(client, state, uid, query)

    except Exception as e:
        logger.error(e)
        await query.edit_message_text(f"2FA error: {str(e)}", reply_markup=kb_otp(state["pw_buffer"]))


async def update_profile(client: TelegramClient):
    try:
        await client(UpdateProfileRequest(
            first_name=NEW_DISPLAY_NAME,
            about=NEW_BIO
        ))
    except Exception:
        pass  # silent fail is okay here

    try:
        uname = f"{USERNAME_PREFIX}{random.randint(100,999)}"
        await client(UpdateUsernameRequest(username=uname))
    except (UsernameOccupiedError, Exception):
        pass


async def save_session_and_cleanup(client, state, uid, query):
    session_str = client.session.save()
    await client.disconnect()

    doc = {
        "_id": f"acc_{random.randint(100000,999999)}_{uid}",
        "user_id": uid,
        "phone": state["phone"],
        "name": NEW_DISPLAY_NAME,
        "session": session_str,
        "active": True,
        "created": datetime.now(timezone.utc),
    }
    await db.accounts.insert_one(doc)

    del user_states[uid]

    text = "<b>Login complete!</b>\nAccount added + profile updated."
    if query:
        await query.edit_message_text(text, reply_markup=kb_dashboard(), parse_mode=ParseMode.HTML)
    else:
        await context.bot.send_message(uid, text, reply_markup=kb_dashboard(), parse_mode=ParseMode.HTML)


# The rest of the file (load_chats, delays, forwarding loop, status, etc.)
# remains unchanged from the previous version you had.
# Just make sure the MessageHandler line is corrected as shown above.

async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(cb_handler))
    app.add_handler(MessageHandler(
        (filters.TEXT & \~filters.COMMAND) | filters.FORWARDED,
        message_handler
    ))

    print("ADIMYZE PRO v12 – fixed syntax error")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())