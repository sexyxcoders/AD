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
    SessionPasswordInvalidError,
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

# Profile template
PROFILE_NAME = "Nexa"
PROFILE_BIO  = "🔥 Managed by @nexaxoders | Adimyze Pro v12 🚀"
USERNAME_PREFIX = "nexa_by_"

# Logging setup
logging.basicConfig(
    format='%(asctime)s | %(levelname)s | %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Database connection
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DB_NAME]

# Global state management
user_states: Dict[int, Dict[str, Any]] = {}
ad_tasks: Dict[int, asyncio.Task] = {}
clients_cache: Dict[str, TelegramClient] = {}

# ────────────────────────────────────────────────
#                     KEYBOARDS
# ────────────────────────────────────────────────

def kb_welcome() -> InlineKeyboardMarkup:
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

def kb_otp(buffer: str = "", is_2fa: bool = False, phone: str = "") -> InlineKeyboardMarkup:
    if is_2fa:
        display = "•" * len(buffer) + " " * (32 - len(buffer))
        title = "🔐 2FA Password"
    else:
        display = buffer.ljust(5, "█")
        title = f"🔑 OTP Code - {phone}"

    buttons = [
        [InlineKeyboardButton(f"{display}", callback_data="dummy")],
        [InlineKeyboardButton("1", callback_data="otp_1"), 
         InlineKeyboardButton("2", callback_data="otp_2"), 
         InlineKeyboardButton("3", callback_data="otp_3")],
        [InlineKeyboardButton("4", callback_data="otp_4"), 
         InlineKeyboardButton("5", callback_data="otp_5"), 
         InlineKeyboardButton("6", callback_data="otp_6")],
        [InlineKeyboardButton("7", callback_data="otp_7"), 
         InlineKeyboardButton("8", callback_data="otp_8"), 
         InlineKeyboardButton("9", callback_data="otp_9")],
        [InlineKeyboardButton("⌫", callback_data="otp_back"),
         InlineKeyboardButton("0", callback_data="otp_0"),
         InlineKeyboardButton("✅", callback_data="otp_confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_login")],
    ]
    return InlineKeyboardMarkup(buttons)

def kb_accounts(accounts: List[Dict]) -> InlineKeyboardMarkup:
    buttons = []
    for acc in accounts[:12]:
        status = "🟢" if acc.get("active", True) else "🔴"
        phone = acc.get("phone", "Unknown")[-8:]
        acc_id = str(acc["_id"])
        buttons.append([InlineKeyboardButton(f"{status} +{phone}", callback_data=f"acc_{acc_id}")])
    
    buttons.extend([
        [],
        [InlineKeyboardButton("➕ Add New Account", callback_data="add_account")],
        [InlineKeyboardButton("🔙 Dashboard", callback_data="dashboard")],
    ])
    return InlineKeyboardMarkup(buttons)

def kb_confirm_delete(acc_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm Delete", callback_data=f"del_acc_{acc_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="my_accounts")],
    ])

# ────────────────────────────────────────────────
#                   CORE HANDLERS
# ────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
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
        reply_markup=kb_welcome(),
        parse_mode=ParseMode.HTML
    )

async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main callback query handler"""
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    try:
        # Home navigation
        if data == "home":
            await query.edit_message_text("🏠 Main Menu", reply_markup=kb_welcome())
            return

        # Cancel login
        if data == "cancel_login":
            cleanup_user_state(uid)
            await query.edit_message_text("❌ Login cancelled.", reply_markup=kb_dashboard())
            return

        # Static pages
        if data == "support":
            await show_support(query)
            return
        if data == "about":
            await show_about(query)
            return

        # OTP handling
        state = user_states.get(uid)
        if state and state.get("step") in ("otp", "2fa"):
            await handle_otp_callback(uid, data, query)
            return

        # Account actions
        if data.startswith("acc_"):
            acc_id = data[4:]
            await handle_account_action(query, uid, acc_id)
            return
        if data.startswith("del_acc_"):
            acc_id = data[8:]
            await handle_delete_account(query, uid, acc_id)
            return

        # Dashboard handlers
        handlers = {
            "dashboard": show_dashboard,
            "add_account": start_add_account,
            "my_accounts": show_my_accounts,
            "load_chats": load_all_chats,
            "set_ad": start_set_ad,
            "set_delays": show_delays,  # Now implemented
            "status": show_status,
            "start_ads": start_campaign,
            "stop_ads": stop_campaign,
        }

        if data in handlers:
            await handlers[data](query, uid, context)
        else:
            await query.edit_message_text("❓ Unknown action.", reply_markup=kb_dashboard())

    except BadRequest as e:
        logger.warning(f"BadRequest in callback: {e}")
    except Exception as e:
        logger.error(f"Callback handler error: {e}")
        await query.edit_message_text("❌ An error occurred.", reply_markup=kb_dashboard())

# ────────────────────────────────────────────────
#                 ACCOUNT MANAGEMENT
# ────────────────────────────────────────────────

async def start_add_account(query, uid: int, context):
    """Start account addition process"""
    user_states[uid] = {"step": "phone"}
    await query.edit_message_text(
        "📱 <b>Add New Account</b>\n\n"
        "Send phone number in <b>international format</b>:\n\n"
        "<code>+12025550123</code>\n<code>+919876543210</code>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="dashboard")]]),
        parse_mode=ParseMode.HTML
    )

async def handle_phone_message(uid: int, phone: str, message):
    """Handle phone number input"""
    if not re.match(r'^\+[1-9]\d{10,14}$', phone):
        await message.reply_text(
            "❌ Invalid format!\n\n"
            "Use international format:\n"
            "<code>+12025550123</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="dashboard")]])
        )
        return

    client = TelegramClient(StringSession(), API_ID, API_HASH)
    
    try:
        await client.connect()
        
        if await client.is_user_authorized():
            await message.reply_text("✅ This session is already authorized.")
            await client.disconnect()
            return

        sent_code = await client.send_code_request(phone)
        
        user_states[uid] = {
            "step": "otp",
            "phone": phone,
            "hash": sent_code.phone_code_hash,
            "buffer": "",
            "client": client,
            "phone_code": sent_code.phone_code if hasattr(sent_code, 'phone_code') else None
        }

        await message.reply_text(
            f"✅ Code sent to <b>{phone}</b>\n\n"
            f"Enter 5-digit code below:",
            reply_markup=kb_otp("", False, phone),
            parse_mode=ParseMode.HTML
        )

    except FloodWaitError as e:
        await message.reply_text(f"⏳ Rate limited. Wait {e.seconds//60 + 1} minutes.")
        await client.disconnect()
    except PhoneNumberInvalidError:
        await message.reply_text("❌ Invalid phone number.")
        await client.disconnect()
    except Exception as e:
        logger.error(f"Phone login error: {e}")
        await message.reply_text(f"❌ Error: {str(e)}")
        await client.disconnect()

async def handle_otp_callback(uid: int, data: str, query):
    """Handle OTP button presses"""
    state = user_states.get(uid)
    if not state:
        return

    step = state["step"]
    buffer = state["buffer"]

    if data == "otp_confirm":
        await verify_login(uid, query, step)
        return

    if data == "otp_back":
        state["buffer"] = buffer[:-1]
    elif data.startswith("otp_") and data[4:].isdigit():
        max_len = 5 if step == "otp" else 32
        if len(buffer) < max_len:
            state["buffer"] += data[4:]

    # Update display
    is_2fa = step == "2fa"
    phone = state.get("phone", "")
    await query.edit_message_text(
        f"<b>{'🔐 2FA Password' if is_2fa else f'🔑 OTP - {phone}'}</b>\n\n"
        f"<code>{'•'*len(state['buffer']) if is_2fa else state['buffer'].ljust(5, '█')}</code>",
        reply_markup=kb_otp(state["buffer"], is_2fa, phone),
        parse_mode=ParseMode.HTML
    )

async def verify_login(uid: int, query, step: str):
    """Verify OTP or 2FA password"""
    state = user_states[uid]
    code = state["buffer"]

    client: TelegramClient = state["client"]

    try:
        if step == "otp":
            await client.sign_in(
                phone=state["phone"], 
                code=code, 
                phone_code_hash=state["hash"]
            )
        else:  # 2fa
            await client.sign_in(password=code)

        await finalize_account_setup(uid, query, client)

    except SessionPasswordNeededError:
        state["step"] = "2fa"
        state["buffer"] = ""
        await query.edit_message_text(
            "🔐 <b>2FA Required</b>\n\nEnter your 2FA password:",
            reply_markup=kb_otp("", True, state["phone"]),
            parse_mode=ParseMode.HTML
        )
    except (PhoneCodeInvalidError, SessionPasswordInvalidError):
        state["buffer"] = ""
        await query.edit_message_text(
            "❌ Wrong code/password!\nTry again:",
            reply_markup=kb_otp("", step == "2fa", state["phone"]),
            parse_mode=ParseMode.HTML
        )
    except PhoneCodeEmptyError:
        state["buffer"] = ""
        await query.edit_message_text(
            "❌ Empty code!\nEnter valid code:",
            reply_markup=kb_otp("", False, state["phone"]),
            parse_mode=ParseMode.HTML
        )
    except FloodWaitError as e:
        await query.edit_message_text(f"⏳ Flood wait: {e.seconds//60 + 1} min")
    except Exception as e:
        logger.error(f"Login verification error: {e}")
        await query.edit_message_text(f"❌ Error: {str(e)}")
        cleanup_user_state(uid)

async def finalize_account_setup(uid: int, query, client: TelegramClient):
    """Complete account setup and save to database"""
    try:
        # Update profile
        await client(UpdateProfileRequest(
            first_name=PROFILE_NAME, 
            about=PROFILE_BIO
        ))

        # Try to set username
        for attempt in range(5):
            uname = f"{USERNAME_PREFIX}{random.randint(1000, 9999)}"
            try:
                await client(UpdateUsernameRequest(username=uname))
                break
            except UsernameOccupiedError:
                if attempt == 4:
                    logger.warning(f"Could not set username for {state['phone']}")

        # Save session
        session_str = client.session.save()

        # Save to database
        doc = {
            "_id": f"acc_{random.randint(100000, 999999)}_{uid}",
            "user_id": uid,
            "phone": user_states[uid]["phone"],
            "session": session_str,
            "active": True,
            "created": datetime.now(timezone.utc),
            "username": uname if attempt < 4 else None
        }
        await db.accounts.insert_one(doc)

        await query.edit_message_text(
            f"✅ <b>Account Added Successfully!</b>\n\n"
            f"📱 Phone: <code>{user_states[uid]['phone'][-8:]}</code>\n"
            f"👤 Profile updated\n"
            f"💾 Session saved",
            reply_markup=kb_dashboard(),
            parse_mode=ParseMode.HTML
        )

    except Exception as e:
        logger.error(f"Account setup error: {e}")
        await query.edit_message_text(
            f"⚠️ Partial success\nSaved account but profile update failed:\n<code>{str(e)}</code>",
            reply_markup=kb_dashboard(),
            parse_mode=ParseMode.HTML
        )
    finally:
        cleanup_user_state(uid)
        await client.disconnect()

def cleanup_user_state(uid: int):
    """Clean up user login state"""
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
    """Show support page"""
    await query.edit_message_text(
        "📞 <b>Support & Contact</b>\n\n"
        "👨‍💻 Developer: @nexaxoders\n"
        "📢 Channel: t.me/testttxs\n\n"
        "💬 For issues or features:\nContact developer directly",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👨‍💻 Contact Developer", url="https://t.me/nexaxoders")],
            [InlineKeyboardButton("📢 Channel", url=CHANNEL_LINK)],
            [InlineKeyboardButton("🏠 Home", callback_data="home")]
        ]),
        parse_mode=ParseMode.HTML
    )

async def show_about(query):
    """Show about page"""
    await query.edit_message_text(
        "ℹ️ <b>About ADIMYZE PRO v12</b>\n\n"
        "🤖 Professional Telegram marketing automation\n\n"
        "⚠️ <b>Use responsibly</b>\n"
        "• Respect Telegram ToS\n"
        "• Don't spam\n"
        "• Rate limits respected\n\n"
        "👨‍💻 Made with ❤️ by @nexaxoders",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="home")]]),
        parse_mode=ParseMode.HTML
    )

async def show_dashboard(query, uid: int, _):
    """Show main dashboard"""
    acc_count = await db.accounts.count_documents({"user_id": uid, "active": True})
    user_doc = await db.users.find_one({"user_id": uid}) or {}
    chat_count = len(user_doc.get("chats", []))
    has_ad = bool(user_doc.get("ad_message"))
    running = user_doc.get("running", False)

    text = f"""
🚀 <b>DASHBOARD</b>

📱 Active Accounts: <b>{acc_count}</b>
💬 Loaded Chats: <b>{chat_count}</b>
📢 Ad Message: <b>{'✅ Set' if has_ad else '❌ Not set'}</b>
⚡ Campaign: <b>{'🟢 RUNNING' if running else '🔴 STOPPED'}</b>
    """
    await query.edit_message_text(text, reply_markup=kb_dashboard(), parse_mode=ParseMode.HTML)

async def show_my_accounts(query, uid: int, _):
    """Show user accounts"""
    accs = await db.accounts.find({"user_id": uid}).sort("created", -1).to_list(20)
    if not accs:
        text = "👥 <b>No accounts yet</b>\n\nAdd your first account to get started!"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Account", callback_data="add_account")],
            [InlineKeyboardButton("🔙 Dashboard", callback_data="dashboard")]
        ]), parse_mode=ParseMode.HTML)
        return
    
    text = f"👥 <b>My Accounts ({len(accs)})</b>"
    await query.edit_message_text(text, reply_markup=kb_accounts(accs), parse_mode=ParseMode.HTML)

async def handle_account_action(query, uid: int, acc_id: str):
    """Handle individual account actions"""
    acc = await db.accounts.find_one({"_id": acc_id, "user_id": uid})
    if not acc:
        await query.answer("Account not found!", show_alert=True)
        return
    
    status = "🟢 Active" if acc.get("active", True) else "🔴 Inactive"
    phone = acc.get("phone", "Unknown")[-8:]
    
    text = f"""
📱 <b>Account Details</b>

Phone: <code>+{phone}</code>
Status: <b>{status}</b>
ID: <code>{acc_id}</code>
Created: {acc.get('created', datetime.now()).strftime('%Y-%m-%d')}

Used in: {len([c for c in (await db.users.find_one({"user_id": uid}) or {}).get('chats', []) if c.get('account_id') == acc_id])} chats
    """
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Toggle Status", callback_data=f"toggle_{acc_id}")],
        [InlineKeyboardButton("🗑️ Delete Account", callback_data=f"confirm_del_{acc_id}")],
        [InlineKeyboardButton("🔙 Back", callback_data="my_accounts")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

async def handle_delete_account(query, uid: int, acc_id: str):
    """Handle account deletion confirmation"""
    acc = await db.accounts.find_one({"_id": acc_id, "user_id": uid})
    if not acc:
        await query.answer("Account not found!", show_alert=True)
        return
    
    phone = acc.get("phone", "Unknown")[-8:]
    text = f"🗑️ <b>Delete Account?</b>\n\nPhone ending: <code>{phone}</code>\n\nThis action cannot be undone!"
    
    await query.edit_message_text(text, reply_markup=kb_confirm_delete(acc_id), parse_mode=ParseMode.HTML)

# ────────────────────────────────────────────────
#                 CHAT LOADING
# ────────────────────────────────────────────────

async def load_all_chats(query, uid: int, _):
    """Load all chats from all accounts"""
    accounts = await db.accounts.find({"user_id": uid, "active": True}).to_list(50)
    if not accounts:
        await query.edit_message_text("❌ No active accounts found!", reply_markup=kb_dashboard())
        return

    await query.edit_message_text("🔄 Loading chats from all accounts...", reply_markup=kb_dashboard())

    total_chats = 0
    for acc in accounts:
        try:
            client = TelegramClient(StringSession(acc["session"]), API_ID, API_HASH)
            await client.connect()
            
            if not await client.is_user_authorized():
                await client.disconnect()
                continue

            chats = []
            async for dialog in client.iter_dialogs(limit=200):
                if (isinstance(dialog.entity, InputPeerChannel) and 
                    dialog.entity.id and dialog.entity.id < 0):
                    chats.append({
                        "chat_id": dialog.entity.id,
                        "access_hash": getattr(dialog.entity, 'access_hash', 0),
                        "title": getattr(dialog.entity, 'title', 'Unknown'),
                        "account_id": acc["_id"]
                    })

            if chats:
                await db.users.update_one(
                    {"user_id": uid},
                    {"$addToSet": {"chats": {"$each": chats}}},
                    upsert=True
                )
                total_chats += len(chats)

            await client.disconnect()
            await asyncio.sleep(2)  # Rate limit protection

        except Exception as e:
            logger.error(f"Chat loading failed for {acc.get('phone', 'unknown')}: {e}")

    user_doc = await db.users.find_one({"user_id": uid}) or {}
    final_count = len(user_doc.get("chats", []))
    
    await query.edit_message_text(
        f"✅ <b>Chats Loaded Successfully!</b>\n\n"
        f"📊 Total unique chats: <b>{final_count}</b>",
        reply_markup=kb_dashboard(),
        parse_mode=ParseMode.HTML
    )

# ────────────────────────────────────────────────
#                    ADVERTISING
# ────────────────────────────────────────────────

async def start_set_ad(query, uid: int, _):
    """Start ad message setup"""
    user_states[uid] = {"step": "wait_ad"}
    await query.edit_message_text(
        "📢 <b>Set Advertisement</b>\n\n"
        "👉 <b>Forward ONE message</b> from your <u>Saved Messages</u>\n\n"
        "✅ This will be sent to all target chats\n"
        "📱 Supports: Text, Photos, Videos, Files, etc.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="dashboard")]]),
        parse_mode=ParseMode.HTML
    )

async def handle_ad_forward(uid: int, message):
    """Handle forwarded ad message"""
    if not message.forward_origin:
        return False

    # Check if from saved messages (self)
    is_from_self = False
    try:
        if hasattr(message.forward_origin, 'sender_user'):
            is_from_self = message.forward_origin.sender_user.is_self
        elif hasattr(message.forward_origin, 'from_id'):
            is_from_self = message.forward_origin.from_id.user_id == message.from_user.id
    except:
        pass

    if not is_from_self:
        await message.reply_text(
            "❌ Please forward from <b>YOUR Saved Messages</b> only!\n\n"
            "📱 Saved Messages → Forward message here",
            parse_mode=ParseMode.HTML
        )
        return True

    # Save ad message
    ad_data = {
        "from_peer": "me",
        "msg_id": message.forward_origin.message_id,
        "chat_id": message.chat.id,
        "message_id": message.message_id,
        "text": message.text or message.caption or "",
        "saved": datetime.now(timezone.utc)
    }

    await db.users.update_one(
        {"user_id": uid},
        {"$set": {"ad_message": ad_data}},
        upsert=True
    )

    await message.reply_text(
        "✅ <b>Ad Message Saved!</b>\n\n"
        f"📝 Preview: <i>{ad_data['text'][:100]}...</i>\n"
        "🚀 Ready for campaigns!",
        reply_markup=kb_dashboard(),
        parse_mode=ParseMode.HTML
    )
    
    user_states.pop(uid, None)
    return True

async def start_campaign(query, uid: int, context):
    """Start advertising campaign"""
    user = await db.users.find_one({"user_id": uid})
    if not user:
        await query.answer("Please setup first!", show_alert=True)
        return
        
    if not user.get("ad_message"):
        await query.answer("Set ad message first!", show_alert=True)
        return
        
    if not user.get("chats"):
        await query.answer("Load chats first!", show_alert=True)
        return

    # Start campaign
    await db.users.update_one({"user_id": uid}, {"$set": {"running": True}})

    if uid in ad_tasks and not ad_tasks[uid].done():
        ad_tasks[uid].cancel()

    task = asyncio.create_task(run_campaign(uid))
    ad_tasks[uid] = task

    await query.edit_message_text(
        "🚀 <b>Campaign Started!</b>\n\n"
        f"📱 Accounts: {await db.accounts.count_documents({'user_id': uid, 'active': True})}\n"
        f"💬 Chats: {len(user.get('chats', []))}\n"
        f"⏱️ Anti-flood active\n\n"
        "👀 Check <b>Status</b> for progress",
        reply_markup=kb_dashboard(),
        parse_mode=ParseMode.HTML
    )

async def stop_campaign(query, uid: int, _):
    """Stop advertising campaign"""
    if uid in ad_tasks:
        ad_tasks[uid].cancel()
        del ad_tasks[uid]

    await db.users.update_one({"user_id": uid}, {"$set": {"running": False}})
    
    await query.edit_message_text(
        "⛔ <b>Campaign Stopped</b>\n\n"
        "All tasks cancelled successfully.",
        reply_markup=kb_dashboard(),
        parse_mode=ParseMode.HTML
    )

async def run_campaign(uid: int):
    """Main campaign loop"""
    logger.info(f"Campaign started for user {uid}")
    
    try:
        while True:
            user_doc = await db.users.find_one({"user_id": uid})
            if not user_doc or not user_doc.get("running", False):
                break

            ad = user_doc.get("ad_message")
            chats = user_doc.get("chats", [])
            
            if not ad or not chats:
                await asyncio.sleep(30)
                continue

            cycle_stats = {"sent": 0, "failed": 0, "timestamp": datetime.now(timezone.utc)}
            
            # Process chats in batches
            for i, chat in enumerate(chats[:100]):  # Limit per cycle
                if not (await db.users.find_one({"user_id": uid}) or {}).get("running"):
                    break

                try:
                    acc = await db.accounts.find_one({
                        "_id": chat["account_id"], 
                        "active": True
                    })
                    if not acc:
                        cycle_stats["failed"] += 1
                        continue

                    client = TelegramClient(StringSession(acc["session"]), API_ID, API_HASH)
                    await client.connect()
                    
                    if not await client.is_user_authorized():
                        await client.disconnect()
                        cycle_stats["failed"] += 1
                        continue

                    # Forward message
                    await client.forward_messages(
                        chat["chat_id"],
                        ad["msg_id"],
                        from_peer="me",
                        drop_author=True,
                        silent=True
                    )
                    
                    cycle_stats["sent"] += 1
                    logger.info(f"Sent ad to {chat['title']} using {acc['phone'][-8:]}")
                    
                    await client.disconnect()
                    
                    # Smart delay
                    delay = random.uniform(60, 180)  # 1-3 minutes
                    await asyncio.sleep(delay)

                except (ChatWriteForbiddenError, PeerFloodError) as e:
                    cycle_stats["failed"] += 1
                    logger.warning(f"Send failed {chat.get('title', 'unknown')}: {type(e).__name__}")
                except FloodWaitError as e:
                    cycle_stats["failed"] += 1
                    wait_time = min(e.seconds + 60, 900)  # Max 15 min
                    logger.warning(f"Flood wait: {wait_time}s")
                    await asyncio.sleep(wait_time)
                except Exception as e:
                    cycle_stats["failed"] += 1
                    logger.error(f"Campaign error: {e}")
                finally:
                    try:
                        await client.disconnect()
                    except:
                        pass

            # Log cycle stats
            await db.users.update_one(
                {"user_id": uid},
                {"$push": {"stats": cycle_stats}}
            )

            # Long cycle break
            await asyncio.sleep(random.uniform(1800, 3600))  # 30-60 minutes

    except asyncio.CancelledError:
        logger.info(f"Campaign {uid} cancelled")
    except Exception as e:
        logger.error(f"Campaign {uid} crashed: {e}")
    finally:
        await db.users.update_one({"user_id": uid}, {"$set": {"running": False}})

async def show_status(query, uid: int, _):
    """Show campaign status"""
    user_doc = await db.users.find_one({"user_id": uid}) or {}
    acc_count = await db.accounts.count_documents({"user_id": uid, "active": True})
    
    stats = user_doc.get("stats", [])
    recent_stats = stats[-5:] if stats else []
    
    logs_text = ""
    total_sent = total_failed = 0
    for stat in recent_stats:
        ts = stat["timestamp"].strftime("%H:%M")
        sent = stat["sent"]
        failed = stat["failed"]
        logs_text += f"• {ts}: ✅{sent} ❌{failed}\n"
        total_sent += sent
        total_failed += failed
    
    if not logs_text:
        logs_text = "No activity yet"

    text = f"""
📊 <b>Status Report</b>

📱 Active Accounts: <b>{acc_count}</b>
💬 Total Chats: <b>{len(user_doc.get('chats', []))}</b>
📢 Ad Set: <b>{'✅ Yes' if user_doc.get('ad_message') else '❌ No'}</b>
⚡ Running: <b>{'🟢 Yes' if user_doc.get('running') else '🔴 No'}</b>

📈 <b>Recent Activity:</b>
{logs_text}

💯 Total: ✅{total_sent} ❌{total_failed}
    """
    
    await query.edit_message_text(text, reply_markup=kb_dashboard(), parse_mode=ParseMode.HTML)

async def show_delays(query, uid: int, _):
    """Show delay settings (placeholder for future)"""
    text = """
⏱️ <b>Delay Settings</b>

Current smart delays:
• Message delay: 60-180s
• Cycle delay: 30-60min
• Flood protection: Auto

✅ Already optimized for safety!
    """
    await query.edit_message_text(text, reply_markup=kb_dashboard(), parse_mode=ParseMode.HTML)

# ────────────────────────────────────────────────
#                 MESSAGE HANDLER
# ────────────────────────────────────────────────

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text and forwarded messages"""
    uid = update.effective_user.id
    msg = update.message
    text = msg.text.strip() if msg.text else ""

    state = user_states.get(uid, {})

    # Phone input
    if state.get("step") == "phone" and text.startswith('+'):
        await handle_phone_message(uid, text, msg)
        return

    # Ad message forward
    if state.get("step") == "wait_ad" and msg.forward_origin:
        if await handle_ad_forward(uid, msg):
            return

    # Fallback
    await msg.reply_text(
        "Use the buttons or /start",
        reply_markup=kb_welcome()
    )

# ────────────────────────────────────────────────
#                        MAIN
# ────────────────────────────────────────────────

async def main():
    """Main application entry point"""
    print("🚀 ADIMYZE PRO v12 starting...")
    
    # Test database connection
    try:
        await db.command('ping')
        print("✅ MongoDB connected")
    except Exception as e:
        print(f"❌ MongoDB error: {e}")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(cb_handler))
    app.add_handler(MessageHandler(
        filters.TEXT | filters.FORWARDED,
        message_handler
    ))

    # Start bot
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True, timeout=45)

    print("✅ Bot running! Press Ctrl+C to stop.")

    # Graceful shutdown
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        
        # Cancel all campaigns
        for task in list(ad_tasks.values()):
            if not task.done():
                task.cancel()
        
        # Cleanup
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        
        # Close clients
        for client in clients_cache.values():
            try:
                await client.disconnect()
            except:
                pass
                
        mongo_client.close()
        print("✅ Shutdown complete!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")