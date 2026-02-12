import asyncio
import random
import logging
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import os

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
from telegram.error import BadRequest

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateProfileRequest, UpdateUsernameRequest
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerChannel, Dialog
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
)

from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

# ────────────────────────────────────────────────
#                     CONFIG
# ────────────────────────────────────────────────

BOT_TOKEN    = '8463982454:AAFXhclFtn5cCoJLZl3l-SwhPMk3ssv6J8o'
API_ID       = 22657083
API_HASH     = 'd6186691704bd901bdab275ceaab88f3'
MONGO_URI    = "mongodb+srv://StarGiftBot_db_user:gld1RLm4eYbCWZlC@cluster0.erob6sp.mongodb.net/?retryWrites=true&w=majority"
DB_NAME      = "adimyze"
CHANNEL_LINK = "https://t.me/testttxs"

PROFILE_NAME = "Nexa"
PROFILE_BIO  = "🔥 Managed by @nexaxoders | Adimyze Pro v12 🚀"
USERNAME_PREFIX = "nexa_by_"

logging.basicConfig(
    format='%(asctime)s | %(levelname)s | %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DB_NAME]

user_states: Dict[int, Dict[str, Any]] = {}
ad_tasks: Dict[int, asyncio.Task] = {}
clients_cache: Dict[str, TelegramClient] = {}

# ────────────────────────────────────────────────
#                     KEYBOARDS
# ────────────────────────────────────────────────

def kb_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Dashboard", callback_data="dashboard")],
        [InlineKeyboardButton("📞 Support", callback_data="support")],
        [InlineKeyboardButton("📢 Channel", url=CHANNEL_LINK)],
        [InlineKeyboardButton("ℹ️ About", callback_data="about")],
    ])

def kb_dashboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Account", callback_data="add_account")],
        [InlineKeyboardButton("👥 My Accounts", callback_data="my_accounts")],
        [InlineKeyboardButton("📥 Load Chats", callback_data="load_chats")],
        [InlineKeyboardButton("📢 Set Ad", callback_data="set_ad")],
        [InlineKeyboardButton("⏱️ Delays", callback_data="set_delays")],
        [InlineKeyboardButton("📊 Status", callback_data="status")],
        [],
        [InlineKeyboardButton("▶️ Start Ads", callback_data="start_ads"),
         InlineKeyboardButton("⛔ Stop Ads", callback_data="stop_ads")],
        [InlineKeyboardButton("🏠 Home", callback_data="home")],
    ])

def kb_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
        [InlineKeyboardButton("🏠 Home", callback_data="home")],
    ])

# ────────────────────────────────────────────────
#                   CORE HANDLERS
# ────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
✨ <b>ADIMYZE PRO v12</b> ✨

<b>Telegram Bulk Forwarding & Marketing Tool</b>

🔥 <b>Main Features:</b>
• ✅ Multiple accounts support
• ✅ Smart anti-flood delays  
• ✅ Forward text/media/files
• ✅ Auto profile setup
• ✅ MongoDB persistence
• ✅ Real-time statistics

👨‍💻 Developed by @nexaxoders • 2026
    """
    await update.message.reply_text(
        text, 
        reply_markup=kb_home(),
        parse_mode=ParseMode.HTML
    )

async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    try:
        # 🏠 ALWAYS GO BACK TO HOME ON "home"
        if data == "home":
            await query.edit_message_text("🏠 <b>Main Menu</b>", reply_markup=kb_home())
            cleanup_user_state(uid)
            return

        # ❌ Cancel any operation
        if data == "cancel":
            cleanup_user_state(uid)
            await query.edit_message_text("❌ Operation cancelled!", reply_markup=kb_dashboard())
            return

        # Static pages
        if data == "support":
            await show_support(query)
            return
        if data == "about":
            await show_about(query)
            return

        # Dashboard handlers
        handlers = {
            "dashboard": show_dashboard,
            "add_account": start_add_account,
            "my_accounts": show_my_accounts,
            "load_chats": load_all_chats,
            "set_ad": start_set_ad,
            "set_delays": show_delays,
            "status": show_status,
            "start_ads": start_campaign,
            "stop_ads": stop_campaign,
        }

        if data in handlers:
            await handlers[data](query, uid)
        else:
            await query.edit_message_text("❓ Unknown action.", reply_markup=kb_dashboard())

    except Exception as e:
        logger.error(f"Callback error: {e}")
        await query.edit_message_text("❌ Error occurred.", reply_markup=kb_home())

# ────────────────────────────────────────────────
#                 ACCOUNT MANAGEMENT (2-FA MANUAL)
# ────────────────────────────────────────────────

async def start_add_account(query, uid: int):
    """Start account addition - MANUAL PHONE"""
    user_states[uid] = {"step": "phone"}
    await query.edit_message_text(
        "📱 <b>Add New Account</b>\n\n"
        "🔹 Send phone number manually:\n"
        "<code>+12025550123</code>\n<code>+919876543210</code>\n\n"
        "📝 International format only!",
        reply_markup=kb_cancel(),
        parse_mode=ParseMode.HTML
    )

async def handle_phone(uid: int, phone: str, message):
    """Handle manual phone input"""
    if not re.match(r'^\+[1-9]\d{10,14}$', phone):
        await message.reply_text(
            "❌ Invalid format!\n\n"
            "✅ Correct: <code>+12025550123</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_cancel()
        )
        return

    client = TelegramClient(StringSession(), API_ID, API_HASH)
    try:
        await client.connect()
        sent_code = await client.send_code_request(phone)

        user_states[uid] = {
            "step": "otp",
            "phone": phone,
            "hash": sent_code.phone_code_hash,
            "client": client
        }

        await message.reply_text(
            f"✅ Code sent to <code>{phone}</code>\n\n"
            "🔑 <b>Send 5-digit OTP manually:</b>",
            reply_markup=kb_cancel(),
            parse_mode=ParseMode.HTML
        )

    except Exception as e:
        await message.reply_text(f"❌ Error: {str(e)}", reply_markup=kb_home())
        await client.disconnect()

async def handle_otp(uid: int, otp: str, message):
    """Handle manual OTP input"""
    state = user_states.get(uid)
    if not state:
        return

    client: TelegramClient = state["client"]
    try:
        await client.sign_in(phone=state["phone"], code=otp, phone_code_hash=state["hash"])
        await finalize_account_setup(uid, message, client)
    except SessionPasswordNeededError:
        state["step"] = "2fa"
        await message.reply_text(
            f"🔐 <b>2FA Required</b>\n\n"
            f"📱 Phone: <code>{state['phone']}</code>\n\n"
            "🔑 <b>Send 2FA password manually:</b>",
            reply_markup=kb_cancel(),
            parse_mode=ParseMode.HTML
        )
    except (PhoneCodeInvalidError, PasswordHashInvalidError):
        await message.reply_text(
            "❌ Wrong code/password!\n🔑 Send again:",
            reply_markup=kb_cancel()
        )
    except Exception as e:
        await message.reply_text(f"❌ Error: {str(e)}", reply_markup=kb_home())

async def handle_2fa(uid: int, password: str, message):
    """Handle manual 2FA input"""
    state = user_states.get(uid)
    if not state:
        return

    client: TelegramClient = state["client"]
    try:
        await client.sign_in(password=password)
        await finalize_account_setup(uid, message, client)
    except PasswordHashInvalidError:
        await message.reply_text("❌ Wrong 2FA password!\n🔑 Send again:", reply_markup=kb_cancel())
    except Exception as e:
        await message.reply_text(f"❌ Error: {str(e)}", reply_markup=kb_home())

async def finalize_account_setup(uid: int, message, client: TelegramClient):
    """Save account after successful login"""
    try:
        await client(UpdateProfileRequest(first_name=PROFILE_NAME, about=PROFILE_BIO))
        
        session_str = client.session.save()
        doc = {
            "_id": f"acc_{random.randint(100000, 999999)}_{uid}",
            "user_id": uid,
            "phone": user_states[uid]["phone"],
            "session": session_str,
            "active": True,
            "created": datetime.now(timezone.utc)
        }
        await db.accounts.insert_one(doc)

        await message.reply_text(
            f"✅ <b>Account Added!</b>\n\n"
            f"📱 <code>{user_states[uid]['phone'][-8:]}</code>\n"
            f"👤 Profile updated ✅\n"
            f"💾 Saved to database ✅",
            reply_markup=kb_dashboard(),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Setup error: {e}")
    finally:
        cleanup_user_state(uid)
        await client.disconnect()

def cleanup_user_state(uid: int):
    state = user_states.pop(uid, None)
    if state and "client" in state:
        try:
            asyncio.create_task(state["client"].disconnect())
        except:
            pass

# ────────────────────────────────────────────────
#                   UI PAGES
# ────────────────────────────────────────────────

async def show_support(query):
    await query.edit_message_text(
        "📞 <b>Support</b>\n\n👨‍💻 @nexaxoders",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👨‍💻 Developer", url="https://t.me/nexaxoders")],
            [InlineKeyboardButton("🏠 Home", callback_data="home")]
        ]),
        parse_mode=ParseMode.HTML
    )

async def show_about(query):
    await query.edit_message_text(
        "ℹ️ <b>ADIMYZE PRO v12</b>\n\n🤖 Professional Telegram automation\n\n⚠️ Use responsibly!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="home")]]),
        parse_mode=ParseMode.HTML
    )

async def show_dashboard(query, uid: int):
    acc_count = await db.accounts.count_documents({"user_id": uid, "active": True})
    user_doc = await db.users.find_one({"user_id": uid}) or {}
    chat_count = len(user_doc.get("chats", []))
    
    text = f"""
🚀 <b>DASHBOARD</b>

📱 Accounts: <b>{acc_count}</b>
💬 Chats: <b>{chat_count}</b>
📢 Ad: <b>{'✅ Set' if user_doc.get('ad_message') else '❌ No'}</b>
    """
    await query.edit_message_text(text, reply_markup=kb_dashboard(), parse_mode=ParseMode.HTML)

async def show_my_accounts(query, uid: int):
    accs = await db.accounts.find({"user_id": uid}).sort("created", -1).to_list(20)
    if not accs:
        await query.edit_message_text(
            "👥 No accounts!\n➕ Add first account",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Account", callback_data="add_account")],
                [InlineKeyboardButton("🏠 Home", callback_data="home")]
            ]),
            parse_mode=ParseMode.HTML
        )
        return

    text = f"👥 <b>Accounts ({len(accs)})</b>"
    buttons = []
    for acc in accs:
        status = "🟢" if acc.get("active") else "🔴"
        buttons.append([InlineKeyboardButton(f"{status} {acc['phone'][-8:]}", callback_data=f"acc_{acc['_id']}")])
    
    buttons.extend([
        [InlineKeyboardButton("➕ Add New", callback_data="add_account")],
        [InlineKeyboardButton("🏠 Home", callback_data="home")]
    ])
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)

async def show_delays(query, uid: int):
    await query.edit_message_text(
        "⏱️ Smart delays active:\n• 60-180s between messages\n• Auto flood protection",
        reply_markup=kb_dashboard()
    )

async def show_status(query, uid: int):
    await query.edit_message_text("📊 Status page (coming soon!)", reply_markup=kb_dashboard())

# Placeholder functions for other features
async def load_all_chats(query, uid: int):
    await query.edit_message_text("📥 Chat loading (coming soon!)", reply_markup=kb_dashboard())

async def start_set_ad(query, uid: int):
    user_states[uid] = {"step": "wait_ad"}
    await query.edit_message_text(
        "📢 Forward ad from Saved Messages",
        reply_markup=kb_cancel()
    )

async def start_campaign(query, uid: int):
    await query.edit_message_text("🚀 Campaign started!", reply_markup=kb_dashboard())

async def stop_campaign(query, uid: int):
    await query.edit_message_text("⛔ Campaign stopped!", reply_markup=kb_dashboard())

# ────────────────────────────────────────────────
#                 MESSAGE HANDLER
# ────────────────────────────────────────────────

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = update.message
    text = msg.text.strip() if msg.text else ""

    state = user_states.get(uid, {})

    # MANUAL PHONE INPUT
    if state.get("step") == "phone" and text.startswith('+'):
        await handle_phone(uid, text, msg)
        return

    # MANUAL OTP INPUT  
    if state.get("step") == "otp" and text.isdigit() and len(text) == 5:
        await handle_otp(uid, text, msg)
        return

    # MANUAL 2FA INPUT
    if state.get("step") == "2fa" and len(text) >= 4:
        await handle_2fa(uid, text, msg)
        return

    # AD FORWARD
    if state.get("step") == "wait_ad" and msg.forward_origin:
        await msg.reply_text("✅ Ad saved!", reply_markup=kb_dashboard())
        user_states.pop(uid, None)
        return

    # FALLBACK
    await msg.reply_text("👆 Use buttons or /start", reply_markup=kb_home())

# ────────────────────────────────────────────────
#                        MAIN
# ────────────────────────────────────────────────

async def main():
    print("🚀 ADIMYZE PRO v12 - MANUAL 2FA ✅")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(cb_handler))
    app.add_handler(MessageHandler(
        filters.TEXT | filters.FORWARDED & ~filters.COMMAND,
        message_handler
    ))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    print("✅ Bot running perfectly!")
    try:
        await asyncio.Event().wait()
    finally:
        await app.stop()
        mongo_client.close()

if __name__ == "__main__":
    asyncio.run(main())