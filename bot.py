import asyncio
import random
import logging
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional

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
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerChannel
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    FloodWaitError,
    UsernameOccupiedError,
    ChatWriteForbiddenError,
    PeerFloodError,
)

from motor.motor_asyncio import AsyncIOMotorClient

# ────────────────────────────────────────────────
#                     CONFIG
# ────────────────────────────────────────────────

BOT_TOKEN    = '8463982454:AAFXhclFtn5cCoJLZl3l-SwhPMk3ssv6J8o'
API_ID       = 22657083
API_HASH     = 'd6186691704bd901bdab275ceaab88f3'
MONGO_URI    = "mongodb+srv://StarGiftBot_db_user:gld1RLm4eYbCWZlC@cluster0.erob6sp.mongodb.net/?retryWrites=true&w=majority"
DB_NAME      = "adimyze"
CHANNEL_LINK = "https://t.me/testttxs"

# Profile template
PROFILE_NAME = "Nexa @nexaxoders"
PROFILE_BIO  = "🔥 Managed by @nexaxoders | Adimyze Pro v12 🚀"
USERNAME_PREFIX = "nexa_by_"

# ────────────────────────────────────────────────
#                   INITIALIZATION
# ────────────────────────────────────────────────

logging.basicConfig(
    format='%(asctime)s | %(levelname)s | %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DB_NAME]

# Global in-memory state (per user)
user_states: Dict[int, Dict[str, Any]] = {}
ad_tasks:   Dict[int, asyncio.Task]     = {}

# ────────────────────────────────────────────────
#                     KEYBOARDS
# ────────────────────────────────────────────────

def kb_welcome() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Dashboard", callback_data="dashboard")],
        [InlineKeyboardButton("📞 Support",    callback_data="support")],
        [InlineKeyboardButton("📢 Channel",    url=CHANNEL_LINK)],
        [InlineKeyboardButton("ℹ️ About",      callback_data="about")],
    ])

def kb_dashboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Account",     callback_data="add_account")],
        [InlineKeyboardButton("👥 My Accounts",     callback_data="my_accounts")],
        [InlineKeyboardButton("📥 Load Chats",      callback_data="load_chats")],
        [InlineKeyboardButton("📢 Set Ad",          callback_data="set_ad")],
        [InlineKeyboardButton("⏱️ Delays",          callback_data="set_delays")],
        [InlineKeyboardButton("📊 Status",          callback_data="status")],
        [],
        [InlineKeyboardButton("▶️ Start Ads", callback_data="start_ads"),
         InlineKeyboardButton("⛔ Stop Ads",  callback_data="stop_ads")],
        [InlineKeyboardButton("🏠 Home", callback_data="home")],
    ])

def kb_otp(buffer: str = "", is_2fa: bool = False) -> InlineKeyboardMarkup:
    if is_2fa:
        display = "•" * len(buffer) + " " * (8 - len(buffer))
        title = "🔐 2FA Password"
    else:
        display = buffer.ljust(6, "█")
        title = "🔑 OTP Code"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{display}", callback_data="dummy")],
        [InlineKeyboardButton("1", callback_data="otp_1"), InlineKeyboardButton("2", callback_data="otp_2"), InlineKeyboardButton("3", callback_data="otp_3")],
        [InlineKeyboardButton("4", callback_data="otp_4"), InlineKeyboardButton("5", callback_data="otp_5"), InlineKeyboardButton("6", callback_data="otp_6")],
        [InlineKeyboardButton("7", callback_data="otp_7"), InlineKeyboardButton("8", callback_data="otp_8"), InlineKeyboardButton("9", callback_data="otp_9")],
        [InlineKeyboardButton("⌫", callback_data="otp_back"),
         InlineKeyboardButton("0", callback_data="otp_0"),
         InlineKeyboardButton("✅", callback_data="otp_confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_login")],
    ])

def kb_simple_accounts(accounts: list) -> InlineKeyboardMarkup:
    buttons = []
    for acc in accounts[:10]:
        status = "🟢" if acc.get("active", True) else "🔴"
        name = acc.get("phone", "???")[-8:]
        buttons.append([InlineKeyboardButton(f"{status} +{name}", callback_data=f"acc_{acc['_id']}")])

    buttons.extend([
        [InlineKeyboardButton("➕ Add New Account", callback_data="add_account")],
        [InlineKeyboardButton("🔙 Dashboard",       callback_data="dashboard")],
    ])
    return InlineKeyboardMarkup(buttons)

# ────────────────────────────────────────────────
#                   CORE HANDLERS
# ────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
✨ <b>ADIMYZE PRO v12</b> ✨

Telegram Bulk Forwarding & Marketing Tool

Main features:
• Multiple accounts support
• Smart anti-flood delays
• Forward text / media / files
• Auto profile & username setup
• MongoDB persistence

Developed by @nexaxoders • 2026
    """
    await update.message.reply_html(text, reply_markup=kb_welcome())

async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    if data == "home":
        await query.edit_message_text("Main Menu", reply_markup=kb_welcome())
        return

    if data == "cancel_login":
        user_states.pop(uid, None)
        await query.edit_message_text("Login cancelled.", reply_markup=kb_dashboard())
        return

    # ────── Static pages ──────
    if data == "support":
        await query.edit_message_text(
            "📞 <b>Support</b>\n\n"
            "→ Developer: @nexaxoders\n"
            "→ Channel: t.me/testttxs",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Contact Dev", url="https://t.me/nexaxoders")],
                [InlineKeyboardButton("Home", callback_data="home")]
            ]),
            parse_mode=ParseMode.HTML
        )
        return

    if data == "about":
        await query.edit_message_text(
            "<b>ADIMYZE PRO v12</b>\n\n"
            "Professional Telegram marketing automation\n"
            "Use responsibly • Respect Telegram ToS",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Home", callback_data="home")]]),
            parse_mode=ParseMode.HTML
        )
        return

    # ────── OTP / 2FA handling ──────
    state = user_states.get(uid)
    if state and state.get("step") in ("otp", "2fa"):
        await handle_otp_press(uid, data, query)
        return

    # ────── Dashboard actions ──────
    handlers = {
        "dashboard":   show_dashboard,
        "add_account": start_add_account,
        "my_accounts": show_my_accounts,
        "load_chats":  load_all_chats,
        "set_ad":      start_set_ad,
        "set_delays":  start_set_delays,   # stub — implement if needed
        "status":      show_status,
        "start_ads":   start_campaign,
        "stop_ads":    stop_campaign,
    }

    if data in handlers:
        await handlers[data](query, uid, context)
    else:
        await query.edit_message_text("Unknown action.", reply_markup=kb_dashboard())

# ────────────────────────────────────────────────
#                 ACCOUNT LOGIN FLOW
# ────────────────────────────────────────────────

async def start_add_account(query, uid: int, _=None):
    user_states[uid] = {"step": "phone"}
    await query.edit_message_text(
        "📱 <b>Add new account</b>\n\n"
        "Send phone number in international format:\n"
        "<code>+12025550123</code>",
        reply_markup=kb_dashboard(),
        parse_mode=ParseMode.HTML
    )

async def handle_phone_input(uid: int, phone: str, message: Update.message):
    if not re.match(r'^\+[1-9]\d{6,14}$', phone):
        await message.reply_text("Invalid phone format. Example: <code>+919876543210</code>")
        return

    client = TelegramClient(StringSession(), API_ID, API_HASH)
    try:
        await client.connect()
        if await client.is_user_authorized():
            await message.reply_text("This session is already logged in.")
            return

        code = await client.send_code_request(phone)

        user_states[uid] = {
            "step": "otp",
            "phone": phone,
            "hash": code.phone_code_hash,
            "buffer": "",
            "client": client,           # kept connected
        }

        await message.reply_html(
            f"Code sent to <b>{phone}</b>\n\nEnter 5-digit code:",
            reply_markup=kb_otp()
        )

    except FloodWaitError as e:
        await message.reply_text(f"⏳ Flood wait: {e.seconds // 60 + 1} minutes")
    except Exception as e:
        logger.exception("Login initiation failed")
        await message.reply_text(f"Error: {str(e)}")
    # do NOT disconnect here — kept for OTP step

async def handle_otp_press(uid: int, data: str, query):
    if not (state := user_states.get(uid)):
        return

    step   = state["step"]
    buffer = state["buffer"]

    if data == "otp_confirm":
        if step == "otp" and len(buffer) == 5:
            await verify_code(uid, query)
        elif step == "2fa" and buffer:
            await verify_password(uid, query)
        return

    if data == "otp_back":
        state["buffer"] = buffer[:-1]
    elif data.startswith("otp_") and data[4:].isdigit():
        if len(buffer) < (5 if step == "otp" else 32):
            state["buffer"] += data[4:]

    # Redraw
    is_2fa = step == "2fa"
    display = "•" * len(buffer) if is_2fa else buffer.ljust(5, "█")
    title = "🔐 2FA Password" if is_2fa else f"🔑 OTP • {state['phone']}"

    await query.edit_message_text(
        f"<b>{title}</b>\n\n<code>{display}</code>",
        reply_markup=kb_otp(buffer, is_2fa),
        parse_mode=ParseMode.HTML
    )

async def verify_code(uid: int, query):
    state = user_states[uid]
    code = state["buffer"]

    try:
        await state["client"].sign_in(state["phone"], code, phone_code_hash=state["hash"])
        await finalize_account(uid, query)

    except SessionPasswordNeededError:
        state.update({"step": "2fa", "buffer": ""})
        await query.edit_message_text(
            "🔐 <b>Two-factor authentication required</b>\n\nEnter password:",
            reply_markup=kb_otp("", True),
            parse_mode=ParseMode.HTML
        )
        return

    except PhoneCodeInvalidError:
        state["buffer"] = ""
        await query.edit_message_text("❌ Wrong code. Try again.", reply_markup=kb_otp())
    except Exception as e:
        logger.exception("Sign-in failed")
        await query.edit_message_text(f"Error: {str(e)}")
        cleanup_login_state(uid)

async def verify_password(uid: int, query):
    state = user_states[uid]
    try:
        await state["client"].sign_in(password=state["buffer"])
        await finalize_account(uid, query)
    except Exception as e:
        state["buffer"] = ""
        await query.edit_message_text(f"❌ Wrong password.\n\nTry again:", reply_markup=kb_otp("", True))
        logger.exception("2FA failed")

async def finalize_account(uid: int, query):
    state = user_states[uid]
    client: TelegramClient = state["client"]

    try:
        # Customize profile
        await client(UpdateProfileRequest(first_name=PROFILE_NAME, about=PROFILE_BIO))

        # Try to set random username
        for _ in range(3):
            uname = f"{USERNAME_PREFIX}{random.randint(1000,9999)}"
            try:
                await client(UpdateUsernameRequest(username=uname))
                break
            except UsernameOccupiedError:
                continue

        session_str = client.session.save()

        doc = {
            "_id": f"acc_{random.randint(100_000, 999_999)}_{uid}",
            "user_id": uid,
            "phone": state["phone"],
            "session": session_str,
            "active": True,
            "created": datetime.now(timezone.utc),
        }
        await db.accounts.insert_one(doc)

        await query.edit_message_text(
            "✅ <b>Account added successfully!</b>\nProfile updated.",
            reply_markup=kb_dashboard(),
            parse_mode=ParseMode.HTML
        )

    except Exception as e:
        logger.exception("Profile / save failed")
        await query.edit_message_text(f"Partial success — error: {str(e)}")
    finally:
        cleanup_login_state(uid)
        await client.disconnect()

def cleanup_login_state(uid: int):
    state = user_states.pop(uid, None)
    if state and "client" in state:
        asyncio.create_task(state["client"].disconnect())

# ────────────────────────────────────────────────
#                   OTHER UI ACTIONS
# ────────────────────────────────────────────────

async def show_dashboard(query, uid: int, _=None):
    acc_count = await db.accounts.count_documents({"user_id": uid, "active": True})
    user_doc = await db.users.find_one({"user_id": uid}) or {}
    chat_count = len(user_doc.get("chats", []))
    has_ad = bool(user_doc.get("ad_message"))
    running = user_doc.get("running", False)

    text = f"""
<b>📊 Dashboard</b>

Accounts ...... {acc_count}
Chats ......... {chat_count}
Ad message .... {'✅' if has_ad else '❌'}
Campaign ...... {'🟢 Running' if running else '🔴 Stopped'}
    """
    await query.edit_message_text(text, reply_markup=kb_dashboard(), parse_mode=ParseMode.HTML)

async def show_my_accounts(query, uid: int, _=None):
    accs = await db.accounts.find({"user_id": uid}).sort("created", -1).to_list(12)
    text = f"<b>My Accounts ({len(accs)})</b>" if accs else "No accounts yet"
    await query.edit_message_text(text, reply_markup=kb_simple_accounts(accs), parse_mode=ParseMode.HTML)

async def load_all_chats(query, uid: int, _=None):
    accounts = await db.accounts.find({"user_id": uid, "active": True}).to_list(30)
    if not accounts:
        await query.edit_message_text("No active accounts.", reply_markup=kb_dashboard())
        return

    total = 0
    for acc in accounts:
        try:
            client = TelegramClient(StringSession(acc["session"]), API_ID, API_HASH)
            await client.connect()
            if not await client.is_user_authorized():
                continue

            async for dialog in client.iter_dialogs():
                if not hasattr(dialog.entity, 'id') or dialog.entity.id >= 0:
                    continue  # skip users & saved messages

                chat = {
                    "chat_id": dialog.entity.id,
                    "access_hash": dialog.entity.access_hash,
                    "title": dialog.entity.title or "No title",
                    "account_id": acc["_id"]
                }
                await db.users.update_one(
                    {"user_id": uid},
                    {"$addToSet": {"chats": chat}},
                    upsert=True
                )
                total += 1

            await client.disconnect()
        except Exception as e:
            logger.error(f"Chat load failed for {acc['phone']}: {e}")

    await query.edit_message_text(f"✅ Loaded ≈{total} chats", reply_markup=kb_dashboard())

# ────────────────────────────────────────────────
#                    AD & CAMPAIGN
# ────────────────────────────────────────────────

async def start_set_ad(query, uid: int, _=None):
    user_states[uid] = {"step": "wait_ad"}
    await query.edit_message_text(
        "Forward **one message** from your <b>Saved Messages</b>\n\n"
        "It will be forwarded to target chats during campaign.",
        reply_markup=kb_dashboard(),
        parse_mode=ParseMode.HTML
    )

async def handle_forwarded_ad(uid: int, message):
    if message.forward_origin and getattr(message.forward_origin.sender_user, "is_self", False):
        data = {
            "from_peer": "me",
            "msg_id": message.forward_origin.message_id,
            "caption": message.caption or message.text or "",
            "saved": datetime.now(timezone.utc)
        }
        await db.users.update_one(
            {"user_id": uid},
            {"$set": {"ad_message": data}},
            upsert=True
        )
        await message.reply_text("✅ Ad message saved.", reply_markup=kb_dashboard())
        user_states.pop(uid, None)
    else:
        await message.reply_text("Please forward from <b>Saved Messages</b> (yourself).")

async def start_campaign(query, uid: int, context):
    user = await db.users.find_one({"user_id": uid})
    if not user or not user.get("ad_message") or not user.get("chats"):
        await query.answer("Missing ad message or chats", show_alert=True)
        return

    await db.users.update_one({"user_id": uid}, {"$set": {"running": True}})

    if uid in ad_tasks:
        ad_tasks[uid].cancel()

    task = asyncio.create_task(run_campaign_loop(uid))
    ad_tasks[uid] = task

    await query.edit_message_text("🚀 Campaign started", reply_markup=kb_dashboard())

async def stop_campaign(query, uid: int, _=None):
    if uid in ad_tasks:
        ad_tasks[uid].cancel()
        del ad_tasks[uid]

    await db.users.update_one({"user_id": uid}, {"$set": {"running": False}})
    await query.edit_message_text("⛔ Campaign stopped", reply_markup=kb_dashboard())

async def run_campaign_loop(uid: int):
    try:
        while True:
            doc = await db.users.find_one({"user_id": uid})
            if not doc or not doc.get("running"):
                break

            ad = doc["ad_message"]
            chats = doc.get("chats", [])[:80]  # safety limit per cycle

            sent = failed = 0

            for chat in chats:
                if not (await db.users.find_one({"user_id": uid}) or {}).get("running"):
                    break

                acc = await db.accounts.find_one({"_id": chat["account_id"], "active": True})
                if not acc:
                    continue

                client = TelegramClient(StringSession(acc["session"]), API_ID, API_HASH)
                try:
                    await client.connect()
                    if not await client.is_user_authorized():
                        continue

                    peer = InputPeerChannel(chat["chat_id"], chat["access_hash"])

                    await client.forward_messages(
                        peer,
                        ad["msg_id"],
                        from_peer="me",
                        drop_author=True,
                        silent=True
                    )
                    sent += 1
                    await asyncio.sleep(random.uniform(45, 120))  # safer range

                except (ChatWriteForbiddenError, PeerFloodError, FloodWaitError) as e:
                    failed += 1
                    logger.warning(f"Cannot send to {chat['title']}: {type(e).__name__}")
                    if isinstance(e, FloodWaitError):
                        await asyncio.sleep(min(e.seconds, 900))
                except Exception as e:
                    failed += 1
                    logger.error(f"Send error → {chat['title']}: {e}")
                finally:
                    await client.disconnect()

            # Log cycle
            await db.users.update_one(
                {"user_id": uid},
                {"$push": {
                    "logs": {
                        "ts": datetime.now(timezone.utc),
                        "sent": sent,
                        "failed": failed
                    }
                }}
            )

            await asyncio.sleep(1200 + random.randint(0, 600))  # \~20–30 min

    except asyncio.CancelledError:
        logger.info(f"Campaign {uid} cancelled")
    except Exception as e:
        logger.exception(f"Campaign loop crashed {uid}")

async def show_status(query, uid: int, _=None):
    doc = await db.users.find_one({"user_id": uid}) or {}
    text = f"""
<b>Status</b>

Accounts .. {await db.accounts.count_documents({"user_id": uid, "active": True})}
Chats ..... {len(doc.get("chats", []))}
Ad ........ {'Set' if doc.get("ad_message") else 'Not set'}
Running ... {'Yes' if doc.get("running") else 'No'}

Last logs:
""" + "\n".join([f"• {l['ts'].strftime('%H:%M')}  sent:{l['sent']}  fail:{l['failed']}" for l in doc.get("logs", [])[-4:]]) or "No activity"

    await query.edit_message_text(text, reply_markup=kb_dashboard(), parse_mode=ParseMode.HTML)

# ────────────────────────────────────────────────
#                    MESSAGE HANDLER
# ────────────────────────────────────────────────

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = update.message
    text = msg.text.strip() if msg.text else ""

    state = user_states.get(uid, {})

    if state.get("step") == "phone":
        await handle_phone_input(uid, text, msg)
        return

    if state.get("step") == "wait_ad" and msg.forward_origin:
        await handle_forwarded_ad(uid, msg)
        return

    # You can add delay setting, etc. here later

# ────────────────────────────────────────────────
#                        MAIN
# ────────────────────────────────────────────────

async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(cb_handler))
    app.add_handler(MessageHandler(
        (filters.TEXT & \~filters.COMMAND) | filters.FORWARDED,
        message_handler
    ))

    print("ADIMYZE PRO v12  •  starting...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        print("\nShutting down...")
        for t in list(ad_tasks.values()):
            t.cancel()
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())