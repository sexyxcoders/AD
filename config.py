import asyncio
import random
import logging
import re
from datetime import datetime, timezone, timedelta

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
from telethon.tl.types import InputPeerChannel, ChannelParticipantsAdmins, ChatBannedRights
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

# Profile auto-update
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

user_states = {}     # uid → temp state (login, settings)
ad_tasks    = {}     # uid → asyncio.Task for forwarding loop

# ────────────────────────────────────────────────
#                   KEYBOARDS
# ────────────────────────────────────────────────

def kb_home():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Dashboard", callback_data="dashboard")],
        [InlineKeyboardButton("📞 Support", callback_data="support")],
        [InlineKeyboardButton("📢 Channel", url=CHANNEL_LINK)],
    ])


def kb_dashboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Account", callback_data="add_account"),
         InlineKeyboardButton("👥 My Accounts", callback_data="my_accounts")],
        [InlineKeyboardButton("📥 Load Chats", callback_data="load_chats")],
        [InlineKeyboardButton("📢 Set Ad Msg", callback_data="set_ad")],
        [InlineKeyboardButton("⏱️ Set Delays", callback_data="set_delays")],
        [InlineKeyboardButton("▶️ Start Ads", callback_data="start_ads"),
         InlineKeyboardButton("⛔ Stop Ads", callback_data="stop_ads")],
        [InlineKeyboardButton("📈 Status", callback_data="status"),
         InlineKeyboardButton("🔙 Home", callback_data="home")],
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

async def cmd_start(update: Update, _):
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
            "<b>Add Account</b>\nSend phone: <code>+919876543210</code>",
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
            "<b>Set Ad Message</b>\nForward **one message** from your **Saved Messages** now.",
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

    # OTP handling
    if uid in user_states and user_states[uid].get("step") in ("otp", "2fa"):
        if data.startswith("otp_"):
            await handle_otp_digit(uid, data[4:], q)
        elif data == "otp_confirm":
            if user_states[uid]["step"] == "otp":
                await verify_otp(uid, q)
            else:
                await verify_2fa(uid, q)

    else:
        await q.answer("Coming soon...", show_alert=True)


# ────────────────────────────────────────────────
#                   OTP & LOGIN
# ────────────────────────────────────────────────

async def handle_otp_digit(uid: int, char: str, query):
    state = user_states.get(uid, {})
    if state.get("step") not in ("otp", "2fa"):
        return

    key = "otp_buffer" if state["step"] == "otp" else "pw_buffer"
    buf = state.get(key, "")

    if char == "back":
        buf = buf[:-1]
    elif char.isdigit():
        max_len = 6 if state["step"] == "otp" else 64
        if len(buf) < max_len:
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
            await msg.reply_html("Invalid phone format.")
            return
        await begin_login(uid, text, msg)

    elif step == "wait_ad_forward":
        if msg.forward_origin and hasattr(msg.forward_origin, 'sender_user') and msg.forward_origin.sender_user.is_self:
            await save_ad_message(uid, msg.forward_origin.message_id, msg)
        else:
            await msg.reply_html("Forward from <b>Saved Messages</b> please.")

    elif step == "set_delays":
        if not re.match(r'^\d+(\.\d+)?$', text):
            await msg.reply_text("Send a number (seconds)")
            return
        await process_delay(uid, float(text), msg)

    elif step == "2fa":
        user_states[uid]["pw_buffer"] = text.strip()
        await verify_2fa(uid, None)


async def begin_login(uid: int, phone: str, msg):
    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()

        if await client.is_user_authorized():
            await msg.reply_html("Already logged in.")
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

        await msg.reply_html(f"Code sent to {phone}\nEnter OTP:", reply_markup=kb_otp())

    except FloodWaitError as e:
        await msg.reply_html(f"Flood wait {e.seconds//60} min")
    except Exception as e:
        await msg.reply_html(f"Error: {str(e)}")


async def verify_otp(uid: int, query):
    state = user_states.get(uid)
    if not state or state["step"] != "otp":
        return

    code = state["otp_buffer"]
    if len(code) != 6:
        await query.answer("6 digits required", show_alert=True)
        return

    client: TelegramClient = state["client"]

    try:
        await client.sign_in(state["phone"], code, phone_code_hash=state["hash"])
        await update_profile(client, uid, query)
        await save_session_and_cleanup(client, state, uid, query)

    except SessionPasswordNeededError:
        state.update({"step": "2fa", "pw_buffer": ""})
        await query.edit_message_text("<b>2FA required</b>\nEnter password:", reply_markup=kb_otp(""), parse_mode=ParseMode.HTML)

    except PhoneCodeInvalidError:
        await query.edit_message_text("Wrong OTP", reply_markup=kb_otp(code), parse_mode=ParseMode.HTML)

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
        await update_profile(client, uid, query)
        await save_session_and_cleanup(client, state, uid, query)

    except Exception as e:
        logger.error(e)
        await query.edit_message_text(f"2FA error: {str(e)}", reply_markup=kb_otp(state["pw_buffer"]))


async def update_profile(client: TelegramClient, uid: int, query):
    profile_msg = ""
    try:
        await client(UpdateProfileRequest(first_name=NEW_DISPLAY_NAME, about=NEW_BIO))
        profile_msg += "Name & Bio updated\n"
    except Exception as e:
        profile_msg += f"Profile error: {str(e)[:50]}\n"

    try:
        uname = f"{USERNAME_PREFIX}{random.randint(100,999)}"
        await client(UpdateUsernameRequest(username=uname))
        profile_msg += f"Username @{uname}\n"
    except UsernameOccupiedError:
        profile_msg += "Username taken\n"
    except Exception as e:
        profile_msg += f"Username error: {str(e)[:50]}\n"

    if query:
        await query.edit_message_text(f"<b>Profile updated:</b>\n{profile_msg}", parse_mode=ParseMode.HTML)


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
    kb = kb_dashboard()
    if query:
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await context.bot.send_message(uid, text, reply_markup=kb, parse_mode=ParseMode.HTML)


# ────────────────────────────────────────────────
#                   LOAD CHATS
# ────────────────────────────────────────────────

async def load_chats(query, uid: int):
    accounts = await db.accounts.find({"user_id": uid, "active": True}).to_list(20)
    if not accounts:
        await query.edit_message_text("No active accounts to load chats from.", reply_markup=kb_dashboard())
        return

    total_loaded = 0
    for acc in accounts:
        client = TelegramClient(StringSession(acc["session"]), API_ID, API_HASH)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                continue

            dialogs = await client.get_dialogs(limit=500)
            chat_list = []

            for d in dialogs:
                entity = d.entity
                if not hasattr(entity, 'id'):
                    continue

                chat_id = entity.id
                title = getattr(entity, 'title', 'No title')
                is_channel = getattr(entity, 'broadcast', False)
                is_megagroup = getattr(entity, 'megagroup', False)
                is_forum = getattr(entity, 'forum', False)

                # Basic send permission check (try to get rights or assume for small groups)
                can_send = True
                if is_channel or is_megagroup:
                    try:
                        full = await client.get_entity(entity)
                        if hasattr(full, 'default_banned_rights') and full.default_banned_rights.send_messages:
                            can_send = False
                    except:
                        pass  # assume yes if can't check

                if can_send and (is_channel or is_megagroup or getattr(entity, 'group', False)):
                    chat_list.append({
                        "chat_id": chat_id,
                        "access_hash": getattr(entity, 'access_hash', 0),
                        "title": title,
                        "is_forum": is_forum,
                        "is_channel": is_channel,
                        "account_id": acc["_id"]
                    })

            if chat_list:
                await db.users.update_one(
                    {"user_id": uid},
                    {"$addToSet": {"chats": {"$each": chat_list}}},
                    upsert=True
                )
                total_loaded += len(chat_list)

        except Exception as e:
            logger.error(f"Load chats error for acc {acc['_id']}: {e}")
        finally:
            await client.disconnect()

    text = f"<b>Loaded {total_loaded} chats/groups/forums</b>\n(duplicates avoided)"
    await query.edit_message_text(text, reply_markup=kb_dashboard(), parse_mode=ParseMode.HTML)


# ────────────────────────────────────────────────
#                   AD MESSAGE & DELAYS
# ────────────────────────────────────────────────

async def save_ad_message(uid: int, msg_id: int, msg):
    await db.users.update_one(
        {"user_id": uid},
        {"$set": {"ad_message": {"peer": "me", "msg_id": msg_id}}},
        upsert=True
    )
    del user_states[uid]
    await msg.reply_html("<b>Ad saved!</b>", reply_markup=kb_dashboard())


async def show_delays(query, uid):
    user = await db.users.find_one({"user_id": uid}) or {}
    s = user.get("settings", {})
    text = (
        "<b>Delays (seconds)</b>\n\n"
        f"Group: <code>{s.get('group_delay', 60)}</code>\n"
        f"Forum: <code>{s.get('forum_delay', 120)}</code>\n"
        f"Cycle: <code>{s.get('cycle_interval', 1800)}</code>\n\n"
        "Reply with next delay value\n(1→Group, 2→Forum, 3→Cycle, repeat)"
    )
    await query.edit_message_text(text, reply_markup=kb_delays(), parse_mode=ParseMode.HTML)


async def process_delay(uid: int, val: float, msg):
    stage = user_states[uid]["delay_stage"]
    keys = ["group_delay", "forum_delay", "cycle_interval"]
    names = ["Group", "Forum", "Cycle"]

    key = keys[stage % 3]
    name = names[stage % 3]
    delay = max(10, min(14400, round(val)))

    await db.users.update_one(
        {"user_id": uid},
        {"$set": {f"settings.{key}": delay}},
        upsert=True
    )

    user_states[uid]["delay_stage"] = stage + 1

    await msg.reply_html(f"<b>{name} → {delay}s</b>\nSend next or back.", reply_markup=kb_delays())


# ────────────────────────────────────────────────
#                   FORWARDING LOOP
# ────────────────────────────────────────────────

async def start_ad_loop(uid: int, query):
    user = await db.users.find_one({"user_id": uid})
    if not user:
        await query.answer("No config found", show_alert=True)
        return

    if user.get("running", False):
        await query.answer("Already running", show_alert=True)
        return

    if "ad_message" not in user or "chats" not in user or not user["chats"]:
        await query.answer("Set ad message & load chats first", show_alert=True)
        return

    await db.users.update_one({"user_id": uid}, {"$set": {"running": True, "logs": []}})

    task = asyncio.create_task(ad_forward_loop(uid))
    ad_tasks[uid] = task

    await query.edit_message_text("<b>Ads STARTED</b>\nCheck status for progress.", reply_markup=kb_dashboard())


async def stop_ad_loop(uid: int, query):
    if uid in ad_tasks:
        ad_tasks[uid].cancel()
        del ad_tasks[uid]

    await db.users.update_one({"user_id": uid}, {"$set": {"running": False}})
    await query.edit_message_text("<b>Ads STOPPED</b>", reply_markup=kb_dashboard())


async def ad_forward_loop(uid: int):
    while True:
        user = await db.users.find_one({"user_id": uid})
        if not user or not user.get("running", False):
            break

        ad = user.get("ad_message")
        chats = user.get("chats", [])
        s = user.get("settings", {})
        group_d = s.get("group_delay", 60)
        forum_d = s.get("forum_delay", 120)
        cycle_d = s.get("cycle_interval", 1800)

        sent = 0
        errors = 0

        for chat_info in chats:
            if not (await db.users.find_one({"user_id": uid}) or {}).get("running", False):
                break

            acc_id = chat_info["account_id"]
            acc = await db.accounts.find_one({"_id": acc_id})
            if not acc:
                continue

            client = TelegramClient(StringSession(acc["session"]), API_ID, API_HASH)
            try:
                await client.connect()

                entity = InputPeerChannel(chat_info["chat_id"], chat_info["access_hash"])

                reply_to = None  # for forums: if you store topic_id per chat, use it here
                # Example: if 'topic_id' in chat_info: reply_to = chat_info['topic_id']

                await client.forward_messages(
                    entity=entity,
                    messages=ad["msg_id"],
                    from_peer="me",
                    reply_to=reply_to  # for forum topics
                )

                sent += 1
                await log_to_user(uid, f"Sent to {chat_info['title']}")

                delay = forum_d if chat_info.get("is_forum", False) else group_d
                await asyncio.sleep(delay + random.uniform(-10, 20))  # small random variation

            except FloodWaitError as e:
                await log_to_user(uid, f"Flood wait {e.seconds}s")
                await asyncio.sleep(e.seconds + 10)
                errors += 1
            except (ChatWriteForbiddenError, ChatAdminRequiredError):
                await log_to_user(uid, f"No send permission: {chat_info['title']}")
                errors += 1
            except Exception as e:
                await log_to_user(uid, f"Error {chat_info['title']}: {str(e)[:80]}")
                errors += 1
            finally:
                await client.disconnect()

        await log_to_user(uid, f"Cycle done | Sent: {sent} | Errors: {errors}")
        await asyncio.sleep(cycle_d)


async def log_to_user(uid: int, text: str):
    await db.users.update_one(
        {"user_id": uid},
        {"$push": {"logs": {"time": datetime.now(timezone.utc), "msg": text}}},
        upsert=True
    )


# ────────────────────────────────────────────────
#                   STATUS & UI
# ────────────────────────────────────────────────

async def show_status(query, uid: int):
    user = await db.users.find_one({"user_id": uid}) or {}
    acc_count = await db.accounts.count_documents({"user_id": uid, "active": True})
    chat_count = len(user.get("chats", []))
    s = user.get("settings", {})
    logs = user.get("logs", [])[-5:]

    text = (
        "<b>STATUS</b>\n\n"
        f"Accounts: <b>{acc_count}</b>\n"
        f"Loaded chats: <b>{chat_count}</b>\n"
        f"Ad set: <b>{'YES' if user.get('ad_message') else 'NO'}</b>\n"
        f"Running: <b>{'YES' if user.get('running', False) else 'NO'}</b>\n\n"
        f"Group delay: <code>{s.get('group_delay', 60)}s</code>\n"
        f"Forum delay: <code>{s.get('forum_delay', 120)}s</code>\n"
        f"Cycle: <code>{s.get('cycle_interval', 1800)}s</code>\n\n"
        "<b>Last logs:</b>\n" + "\n".join([f"{l['time'].strftime('%H:%M')} {l['msg'][:60]}" for l in logs]) or "No logs yet"
    )

    await query.edit_message_text(text, reply_markup=kb_dashboard(), parse_mode=ParseMode.HTML)


async def show_dashboard(query, uid: int):
    count = await db.accounts.count_documents({"user_id": uid, "active": True})
    text = f"<b>DASHBOARD</b>\nAccounts: <b>{count}</b>\nStatus: {'RUNNING' if (await db.users.find_one({'user_id': uid}) or {}).get('running', False) else 'STOPPED'}\n\nControls:"
    await query.edit_message_text(text, reply_markup=kb_dashboard(), parse_mode=ParseMode.HTML)


async def show_my_accounts(query, uid: int):
    accs = await db.accounts.find({"user_id": uid}).sort("created", -1).to_list(10)
    text = f"<b>Accounts ({len(accs)})</b>" if accs else "<b>No accounts</b>"
    kb = kb_accounts(accs) if accs else InlineKeyboardMarkup([[InlineKeyboardButton("➕ Add", callback_data="add_account")]])
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# ────────────────────────────────────────────────
#                   MAIN
# ────────────────────────────────────────────────

async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(cb_handler))
    app.add_handler(MessageHandler(filters.TEXT & \~filters.COMMAND | filters.FORWARDED, message_handler))

    print("ADIMYZE PRO v12 – Load Chats + Forward Loop ready")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())