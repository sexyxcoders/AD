import asyncio
import random
import logging
import re
from datetime import datetime

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
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    FloodWaitError,
    PhoneCodeExpiredError,
)

from motor.motor_asyncio import AsyncIOMotorClient

# ────────────────────────────────────────────────
#                  CONFIGURATION
# ────────────────────────────────────────────────

BOT_TOKEN  = '8463982454:AAFXhclFtn5cCoJLZl3l-SwhPMk3ssv6J8o'
API_ID     = 22657083
API_HASH   = 'd6186691704bd901bdab275ceaab88f3'

MONGO_URI      = "mongodb+srv://StarGiftBot_db_user:gld1RLm4eYbCWZlC@cluster0.erob6sp.mongodb.net/?retryWrites=true&w=majority"
DB_NAME        = "adimyze"
CHANNEL_LINK   = "https://t.me/testttxs"

# ────────────────────────────────────────────────
#                  INITIALIZATION
# ────────────────────────────────────────────────

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DB_NAME]

# Global in-memory states (consider redis for production)
user_states  = {}   # uid → dict
user_clients = {}   # uid → TelegramClient  (only during login)

# ────────────────────────────────────────────────
#                     KEYBOARDS
# ────────────────────────────────────────────────

def kb_start():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📞 Support", callback_data="support"),
            InlineKeyboardButton("📊 Dashboard", callback_data="dashboard")
        ],
        [InlineKeyboardButton("📢 Channel", url=CHANNEL_LINK)],
    ])


def kb_dashboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add Account", callback_data="add_account"),
            InlineKeyboardButton("👥 My Accounts", callback_data="my_accounts")
        ],
        [
            InlineKeyboardButton("📝 Set Ad", callback_data="set_ad"),
            InlineKeyboardButton("⏱️ Set Delay", callback_data="set_delay")
        ],
        [
            InlineKeyboardButton("▶️ Start Ads", callback_data="start_ads"),
            InlineKeyboardButton("⏹️ Stop Ads", callback_data="stop_ads")
        ],
        [
            InlineKeyboardButton("📈 Analytics", callback_data="analytics"),
            InlineKeyboardButton("🔙 Back", callback_data="back_to_start")
        ],
    ])


def kb_otp(buffer=""):
    display = (buffer + "______")[:6]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔢 {display}", callback_data="dummy")],
        [
            InlineKeyboardButton("1", callback_data="otp_1"),
            InlineKeyboardButton("2", callback_data="otp_2"),
            InlineKeyboardButton("3", callback_data="otp_3"),
        ],
        [
            InlineKeyboardButton("4", callback_data="otp_4"),
            InlineKeyboardButton("5", callback_data="otp_5"),
            InlineKeyboardButton("6", callback_data="otp_6"),
        ],
        [
            InlineKeyboardButton("7", callback_data="otp_7"),
            InlineKeyboardButton("8", callback_data="otp_8"),
            InlineKeyboardButton("9", callback_data="otp_9"),
        ],
        [
            InlineKeyboardButton("⌫", callback_data="otp_back"),
            InlineKeyboardButton("0", callback_data="otp_0"),
            InlineKeyboardButton("✅", callback_data="otp_confirm"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_login")],
    ])


def kb_accounts(accounts):
    buttons = []
    for acc in accounts[:10]:
        status = "🟢" if acc.get("active", True) else "🔴"
        name   = acc.get("name", acc["phone"][-8:])
        text   = f"{status} {name}"
        buttons.append([InlineKeyboardButton(text, callback_data=f"acc_select_{acc['_id']}")])

    buttons.extend([
        [InlineKeyboardButton("➕ Add New", callback_data="add_account")],
        [InlineKeyboardButton("🔙 Dashboard", callback_data="dashboard")],
    ])
    return InlineKeyboardMarkup(buttons)


# ────────────────────────────────────────────────
#                   HANDLERS
# ────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🔥 <b>ADIMYZE PRO v9.1</b> 🔥\n\n"
        "<b>Professional Telegram Advertisement Tool</b>\n\n"
        "👇 <b>Select action:</b>"
    )
    await update.message.reply_html(text, reply_markup=kb_start())


async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid  = q.from_user.id
    data = q.data

    # ─── Quick exits ─────────────────────────────────────
    if data == "cancel_login":
        user_states.pop(uid, None)
        user_clients.pop(uid, None)
        await q.edit_message_text("🚫 Login cancelled.", reply_markup=kb_start())
        return

    if data == "back_to_start":
        await q.edit_message_text(
            "🔥 <b>Welcome back!</b>\n\nChoose action 👇",
            reply_markup=kb_start(),
            parse_mode=ParseMode.HTML
        )
        return

    # ─── Main menu ───────────────────────────────────────
    if data == "dashboard":
        await show_dashboard(q, uid)
        return

    if data == "support":
        await q.edit_message_text(
            "📞 <b>Support</b>\n\n"
            "👤 @yourusername\n"
            f"📢 {CHANNEL_LINK}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_to_start")]]),
            parse_mode=ParseMode.HTML
        )
        return

    if data == "add_account":
        user_states[uid] = {"step": "phone"}
        await q.edit_message_text(
            "📱 <b>Add Telegram Account</b>\n\n"
            "Send phone number in international format:\n"
            "<code>+919876543210</code>",
            reply_markup=kb_dashboard(),
            parse_mode=ParseMode.HTML
        )
        return

    if data == "my_accounts":
        await show_my_accounts(q, uid)
        return

    # ─── OTP controls ────────────────────────────────────
    if uid in user_states and user_states[uid].get("step") == "otp":
        if data.startswith("otp_"):
            await handle_otp_input(uid, data[4:], q)
            return

        if data == "otp_confirm":
            await verify_otp(uid, q)
            return

    # ─── Placeholder / not implemented yet ───────────────
    await q.answer("⚙️ Feature coming soon...", show_alert=True)


async def handle_otp_input(uid: int, digit: str, query):
    state = user_states.get(uid, {})
    if state.get("step") != "otp":
        return

    buffer: str = state.get("otp_buffer", "")

    if digit == "back":
        buffer = buffer[:-1]
    elif digit.isdigit() and len(buffer) < 6:
        buffer += digit

    user_states[uid]["otp_buffer"] = buffer

    await show_otp_screen(query, uid)


async def show_otp_screen(query, uid: int):
    state = user_states[uid]
    phone  = state["phone"]
    buffer = state.get("otp_buffer", "")
    display = (buffer + "______")[:6]

    text = (
        f"🔐 <b>OTP for {phone}</b>\n\n"
        f"<code>{display}</code>\n\n"
        "Enter 6-digit code using buttons below 👇"
    )

    await query.edit_message_text(
        text,
        reply_markup=kb_otp(buffer),
        parse_mode=ParseMode.HTML
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text.strip()

    if uid not in user_states:
        return

    step = user_states[uid].get("step")

    if step == "phone":
        if not re.match(r'^\+[1-9]\d{6,14}$', text):
            await update.message.reply_html("❌ Invalid format. Use: <code>+12025550123</code>")
            return

        await start_login_flow(uid, text, update.message)


async def start_login_flow(uid: int, phone: str, msg):
    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()

        if await client.is_user_authorized():
            await msg.reply_html("🚫 This number is already logged in somewhere.")
            await client.disconnect()
            return

        sent = await client.send_code_request(phone)

        user_states[uid] = {
            "step": "otp",
            "phone": phone,
            "phone_code_hash": sent.phone_code_hash,
            "otp_buffer": "",
            "client": client,           # temporary — only during login
        }

        user_clients[uid] = client

        await msg.reply_html(
            f"📨 <b>Code sent to {phone}</b>\n\n"
            "Enter the 6-digit code using the buttons below:",
            reply_markup=kb_otp()
        )

    except FloodWaitError as e:
        await msg.reply_html(f"⏳ Flood wait — try again in {e.seconds//60} minutes.")
    except Exception as e:
        logger.exception("Login initiation failed")
        await msg.reply_html(f"❌ Error: {str(e)}")


async def verify_otp(uid: int, query):
    state = user_states.get(uid)
    if not state or state.get("step") != "otp":
        return

    code = state.get("otp_buffer", "")
    if len(code) != 6:
        await query.answer("Enter 6 digits first", show_alert=True)
        return

    client: TelegramClient = state["client"]
    phone = state["phone"]
    hash_ = state["phone_code_hash"]

    try:
        await query.edit_message_text("🔐 Verifying...", parse_mode=ParseMode.HTML)

        await client.sign_in(phone, code, phone_code_hash=hash_)

        session_string = client.session.save()
        await client.disconnect()

        # cleanup
        user_states.pop(uid, None)
        user_clients.pop(uid, None)

        # save account
        doc = {
            "_id": f"acc_{random.randint(100000,999999)}_{uid}",
            "user_id": uid,
            "phone": phone,
            "name": f"Acc {phone[-6:]}",
            "session": session_string,
            "active": True,
            "created": datetime.utcnow(),
            "stats": {"posts": 0, "last": None},
        }

        await db.accounts.insert_one(doc)

        await query.edit_message_text(
            f"🎉 <b>Login successful!</b>\n\n"
            f"Phone: <code>{phone}</code>\n\n"
            "<b>Account added.</b> You can rename it later.",
            reply_markup=kb_dashboard(),
            parse_mode=ParseMode.HTML
        )

    except PhoneCodeInvalidError:
        await query.edit_message_text(
            "❌ Wrong code.\n\nTry again:",
            reply_markup=kb_otp(state["otp_buffer"]),
            parse_mode=ParseMode.HTML
        )
    except PhoneCodeExpiredError:
        await query.edit_message_text(
            "⌛ Code expired.\nStart over.",
            reply_markup=kb_start(),
            parse_mode=ParseMode.HTML
        )
    except SessionPasswordNeededError:
        await query.edit_message_text(
            "🔐 2FA password required.\n\n"
            "(2FA support coming soon)",
            reply_markup=kb_start(),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.exception("OTP verification failed")
        await query.edit_message_text(f"❌ {str(e)}", reply_markup=kb_start())


async def show_dashboard(query, uid: int):
    count = await db.accounts.count_documents({"user_id": uid})

    text = (
        "📊 <b>DASHBOARD</b>\n\n"
        f"Accounts: <b>{count}</b>\n"
        "Status:   <b>🟥 STOPPED</b>\n\n"
        "<b>Controls:</b>"
    )

    await query.edit_message_text(
        text,
        reply_markup=kb_dashboard(),
        parse_mode=ParseMode.HTML
    )


async def show_my_accounts(query, uid: int):
    accs = await db.accounts.find({"user_id": uid}).sort("created", -1).to_list(12)

    if not accs:
        text = "📭 <b>No accounts yet</b>\nAdd your first one!"
        kb   = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Account", callback_data="add_account")],
            [InlineKeyboardButton("🔙 Dashboard",   callback_data="dashboard")],
        ])
    else:
        text = f"👥 <b>Your Accounts ({len(accs)})</b>"
        kb   = kb_accounts(accs)

    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# ────────────────────────────────────────────────
#                     MAIN
# ────────────────────────────────────────────────

async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))

    app.add_handler(CallbackQueryHandler(cb_handler))

    app.add_handler(MessageHandler(
        filters.TEXT & \~filters.COMMAND,
        message_handler
    ))

    print("🚀 ADIMYZE PRO v9.1  –  OTP + UI fixed")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )

    # keep alive
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())