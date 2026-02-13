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
from telegram.error import BadRequest, TelegramError

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

# ────────────────────────────────────────────────
# CONFIGURATION
# ────────────────────────────────────────────────

BOT_TOKEN = '8463982454:AAErd8EZswKgQ1BNF_r-N8iUH8HQcb293lQ'
API_ID = 22657083
API_HASH = 'd6186691704bd901bdab275ceaab88f3'
MONGO_URI = "mongodb+srv://bot627668:2bEJ56yJSu7vzLws@cluster0.qbw5van.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

BANNER_URL = "https://files.catbox.moe/zttfbe.jpg"

PROFILE_NAME = "Adimyze Pro"
PROFILE_BIO = "🚀 Professional Telegram Marketing Automation | Managed by @nexaxoders"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

db = AsyncIOMotorClient(MONGO_URI)["adimyze"]

# ────────────────────────────────────────────────
# STATE MANAGEMENT
# ────────────────────────────────────────────────

@dataclass
class UserState:
    step: str = "idle"
    phone: str = ""
    phone_code_hash: str = ""
    client: Optional[TelegramClient] = None
    otp_buffer: str = ""
    delay_seconds: int = 300           # default 5 min

user_states: Dict[int, UserState] = {}

# ────────────────────────────────────────────────
# SAFE MESSAGE EDITING
# ────────────────────────────────────────────────

async def safe_edit_or_send(query: Update.callback_query, text: str, reply_markup=None):
    try:
        await query.edit_message_caption(caption=text, reply_markup=reply_markup)
    except BadRequest as e:
        err = str(e).lower()
        if "not modified" in err:
            return
        if "not found" in err or "can't be edited" in err:
            try:
                await query.message.reply_photo(
                    photo=BANNER_URL,
                    caption=text,
                    reply_markup=reply_markup
                )
                await query.message.delete()
            except:
                pass
            return

    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup)
    except:
        try:
            await query.message.reply_text(text=text, reply_markup=reply_markup)
            await query.message.delete()
        except:
            pass

# ────────────────────────────────────────────────
# KEYBOARDS
# ────────────────────────────────────────────────

def kb_start():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("     Dashboard       ", callback_data="nav|dashboard")],
        [InlineKeyboardButton("Updates", url="https://t.me/testttxs"),
         InlineKeyboardButton("Support", url="https://t.me/nexaxoders")],
        [InlineKeyboardButton("     How to Use      ", callback_data="nav|howto")],
        [InlineKeyboardButton("       Powered By    ", url="https://t.me/nexaxoders")]
    ])


def kb_dashboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Accounts", callback_data="acc|add"),
         InlineKeyboardButton("My Accounts", callback_data="acc|list|0")],
        [InlineKeyboardButton("Set Ad Message", callback_data="ad|set"),
         InlineKeyboardButton("Set Interval", callback_data="delay|nav")],
        [InlineKeyboardButton("Start Ads", callback_data="camp|start"),
         InlineKeyboardButton("Stop Ads", callback_data="camp|stop")],
        [InlineKeyboardButton("Delete Accounts", callback_data="acc|del"),
         InlineKeyboardButton("Analytics", callback_data="stat|main")],
        [InlineKeyboardButton("Auto Reply", callback_data="feature|auto"),
         InlineKeyboardButton("Back", callback_data="nav|start")]
    ])


def kb_otp(state: UserState):
    display = (state.otp_buffer + "○" * (5 - len(state.otp_buffer)))[:5]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"OTP: {display}", callback_data="ignore")],
        [InlineKeyboardButton("1", callback_data="otp|1"),
         InlineKeyboardButton("2", callback_data="otp|2"),
         InlineKeyboardButton("3", callback_data="otp|3")],
        [InlineKeyboardButton("4", callback_data="otp|4"),
         InlineKeyboardButton("5", callback_data="otp|5"),
         InlineKeyboardButton("6", callback_data="otp|6")],
        [InlineKeyboardButton("7", callback_data="otp|7"),
         InlineKeyboardButton("8", callback_data="otp|8"),
         InlineKeyboardButton("9", callback_data="otp|9")],
        [InlineKeyboardButton("⌫", callback_data="otp|back"),
         InlineKeyboardButton("0", callback_data="otp|0"),
         InlineKeyboardButton("❌ Cancel", callback_data="otp|cancel")],
        [InlineKeyboardButton("Show Code", url="tg://openmessage?user_id=777000")]
    ])


def kb_delay(current: int = 300):
    def emoji(s):
        if s <= 300: return "🔴"
        if s <= 600: return "🟡"
        return "🟢"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"5 min {emoji(300)}", callback_data="setdelay|300"),
         InlineKeyboardButton(f"10 min {emoji(600)}", callback_data="setdelay|600")],
        [InlineKeyboardButton(f"20 min {emoji(1200)}", callback_data="setdelay|1200")],
        [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
    ])


def kb_accounts(accounts: list, page: int = 0):
    page_size = 5
    start = page * page_size
    page_accounts = accounts[start:start + page_size]

    buttons = []
    for acc in page_accounts:
        status = "🟢" if acc.get("active", False) else "🔴"
        phone = acc["phone"]
        buttons.append([InlineKeyboardButton(
            f"{status} ••••{phone[-4:]}",
            callback_data=f"acc|detail|{acc['_id']}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"acc|list|{page-1}"))
    if start + page_size < len(accounts):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"acc|list|{page+1}"))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton("Back", callback_data="nav|dashboard")])
    return InlineKeyboardMarkup(buttons)


def kb_account_detail(acc_id: str, phone: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Delete Account", callback_data=f"acc|delete|{acc_id}")],
        [InlineKeyboardButton("Back to List", callback_data="acc|list|0")],
        [InlineKeyboardButton("Dashboard", callback_data="nav|dashboard")]
    ])


def kb_confirm_delete(acc_id: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, Delete", callback_data=f"acc|confirm_del|{acc_id}"),
         InlineKeyboardButton("❌ No", callback_data="nav|dashboard")]
    ])

# ────────────────────────────────────────────────
# HANDLERS
# ────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "╰_╯ Welcome to @Tecxo Free Ads bot — The Future of Telegram Automation\n\n"
        "• Premium Ad Broadcasting\n"
        "• Smart Delays\n"
        "• Multi-Account Support\n\n"
        "For support contact: @NexaCoders"
    )

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.message.reply_photo(
            photo=BANNER_URL,
            caption=text,
            reply_markup=kb_start()
        )
        try:
            await query.message.delete()
        except:
            pass
    else:
        await update.message.reply_photo(
            photo=BANNER_URL,
            caption=text,
            reply_markup=kb_start()
        )


async def handle_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, dest = query.data.split("|", 1)

    if dest == "start":
        await cmd_start(update, context)

    elif dest == "dashboard":
        text = "╰_╯ DASHBOARD\n\nManage your ad campaigns and accounts:"
        await safe_edit_or_send(query, text, kb_dashboard())

    elif dest == "howto":
        text = (
            "╰_╯ HOW TO USE\n\n"
            "1. Add Account → Host your Telegram account\n"
            "2. Set Ad Message → Create your promotional text\n"
            "3. Set Time Interval → Configure broadcast frequency\n"
            "4. Start Ads → Begin automated broadcasting\n\n"
            "⚠️ Note: Using aggressive intervals may risk account suspension"
        )
        await safe_edit_or_send(
            query, text,
            InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]])
        )


async def handle_account_ops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    action = parts[1]
    user_id = query.from_user.id

    if action == "add":
        user_states[user_id] = UserState(step="phone")
        text = (
            "╰_╯ HOST NEW ACCOUNT\n\n"
            "Secure Account Hosting\n\n"
            "Enter your phone number with country code:\n"
            "Example: +1234567890"
        )
        await query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]])
        )

    elif action == "list":
        page = int(parts[2])
        accounts = await db.accounts.find({"user_id": user_id}).to_list(None)
        if not accounts:
            await query.answer("No accounts added yet!", show_alert=True)
            await safe_edit_or_send(query, "📱 MY ACCOUNTS\n\nNo accounts yet.", kb_dashboard())
            return

        text = f"📱 MY ACCOUNTS ({len(accounts)})\n\nSelect account:"
        await safe_edit_or_send(query, text, kb_accounts(accounts, page))

    elif action == "detail":
        acc_id = parts[2]
        acc = await db.accounts.find_one({"_id": acc_id, "user_id": user_id})
        if not acc:
            await query.answer("Account not found", show_alert=True)
            return
        status = "Active" if acc.get("active") else "Inactive"
        text = f"📱 ACCOUNT DETAILS\n\nPhone: {acc['phone']}\nStatus: {status}"
        await safe_edit_or_send(query, text, kb_account_detail(acc_id, acc["phone"]))

    elif action == "delete":
        acc_id = parts[2]
        acc = await db.accounts.find_one({"_id": acc_id, "user_id": user_id})
        if not acc:
            await query.answer("Account not found", show_alert=True)
            return
        text = f"⚠️ DELETE ACCOUNT\n\nConfirm removal of {acc['phone']}?"
        await safe_edit_or_send(query, text, kb_confirm_delete(acc_id))

    elif action == "confirm_del":
        acc_id = parts[2]
        result = await db.accounts.delete_one({"_id": acc_id, "user_id": user_id})
        msg = "✅ Account deleted!" if result.deleted_count else "❌ Delete failed!"
        await query.answer(msg, show_alert=True)
        await safe_edit_or_send(query, "╰_╯ DASHBOARD", kb_dashboard())

    elif action == "del":
        count = await db.accounts.count_documents({"user_id": user_id})
        if count == 0:
            await query.answer("No accounts to delete!", show_alert=True)
            return
        text = "🗑️ DELETE ACCOUNTS\nChoose how to proceed:"
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("View & Delete", callback_data="acc|list|0")],
            [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
        ])
        await safe_edit_or_send(query, text, markup)


async def handle_otp_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    state = user_states.get(user_id)

    if not state or state.step != "code":
        await query.answer("Session expired", show_alert=True)
        return

    await query.answer()
    _, action = query.data.split("|", 1)

    if action == "cancel":
        if state.client:
            await state.client.disconnect()
        user_states[user_id] = UserState()
        await query.message.delete()
        await query.message.reply_text("Process cancelled.", reply_markup=kb_dashboard())
        return

    if action == "back":
        state.otp_buffer = state.otp_buffer[:-1]
    elif action.isdigit() and len(state.otp_buffer) < 5:
        state.otp_buffer += action

    masked = " ".join("•" if c.isdigit() else "_" for c in (state.otp_buffer + "     "))[:11:2]

    if len(state.otp_buffer) == 5:
        await finalize_login(user_id, context)
        return

    try:
        await query.edit_message_text(
            f"OTP sent to {state.phone}\n\n"
            f"Current: {masked}\n"
            f"Format: 12345",
            reply_markup=kb_otp(state)
        )
    except BadRequest:
        pass


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    if not state or state.step == "idle":
        return

    text = update.message.text.strip()

    if state.step == "phone":
        phone = "+" + re.sub(r"\D", "", text)
        if not (8 <= len(phone) <= 15):
            await update.message.reply_text("Invalid phone number format.")
            return

        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()

        try:
            sent_code = await client.send_code_request(phone)
            state.client = client
            state.phone = phone
            state.phone_code_hash = sent_code.phone_code_hash
            state.step = "code"
            state.otp_buffer = ""

            await update.message.reply_text(
                f"OTP sent to {phone}\n\nUse the buttons below to enter code.",
                reply_markup=kb_otp(state)
            )
        except FloodWaitError as e:
            await update.message.reply_text(f"⏳ Flood wait: {e.seconds}s")
        except PhoneNumberInvalidError:
            await update.message.reply_text("Invalid phone number.")
        except Exception as e:
            logger.exception("Login initiation failed")
            await update.message.reply_text(f"Error: {str(e)[:120]}")
        finally:
            if state.step != "code":
                await client.disconnect()

    elif state.step == "password":
        await finalize_login(user_id, context, password=text)
        user_states[user_id] = UserState()

    elif state.step == "set_ad":
        if len(text) > 4000:
            await update.message.reply_text("Message too long (max 4000 chars).")
            return

        await db.ads.update_one(
            {"user_id": str(user_id)},
            {"$set": {"text": text, "updated_at": datetime.now(timezone.utc)}},
            upsert=True
        )
        user_states[user_id] = UserState()
        await update.message.reply_text("✅ Ad message saved!", reply_markup=kb_dashboard())


async def finalize_login(user_id: int, context: ContextTypes.DEFAULT_TYPE, password: Optional[str] = None):
    state = user_states.get(user_id)
    if not state or not state.client:
        await context.bot.send_message(user_id, "Session expired.", reply_markup=kb_dashboard())
        return

    try:
        if password:
            await state.client.sign_in(password=password)
        else:
            await state.client.sign_in(
                phone=state.phone,
                code=state.otp_buffer,
                phone_code_hash=state.phone_code_hash
            )

        # Set profile
        try:
            await state.client(UpdateProfileRequest(
                first_name=PROFILE_NAME,
                about=PROFILE_BIO
            ))
        except Exception as e:
            logger.warning(f"Could not update profile: {e}")

        session_str = state.client.session.save()

        await db.accounts.update_one(
            {"user_id": user_id, "phone": state.phone},
            {"$set": {
                "session": session_str,
                "active": True,
                "created_at": datetime.now(timezone.utc),
                "last_used": datetime.now(timezone.utc)
            }},
            upsert=True
        )

        await state.client.disconnect()
        user_states[user_id] = UserState()

        await context.bot.send_message(
            user_id,
            f"✅ Account added!\nPhone: {state.phone}\nProfile updated.",
            reply_markup=kb_dashboard()
        )

    except SessionPasswordNeededError:
        state.step = "password"
        await context.bot.send_message(
            user_id,
            "🔐 2FA required.\nPlease send your cloud password:"
        )
    except PhoneCodeInvalidError:
        await context.bot.send_message(user_id, "Invalid code. Try again.")
    except Exception as e:
        logger.exception("Login finalization failed")
        await context.bot.send_message(user_id, f"Login failed: {str(e)[:140]}")
    finally:
        if state.client and not state.client.is_connected():
            await state.client.disconnect()


# ────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(handle_navigation, pattern=r"^nav\|"))
    app.add_handler(CallbackQueryHandler(handle_account_ops, pattern=r"^acc\|"))
    app.add_handler(CallbackQueryHandler(handle_otp_input, pattern=r"^otp\|"))
    app.add_handler(CallbackQueryHandler(lambda u,c: u.callback_query.answer(), pattern=r"^ignore$"))

    # Text input for phone, password, ad message
    app.add_handler(MessageHandler(filters.TEXT & \~filters.COMMAND, handle_text_input))

    # TODO: implement campaign start/stop + actual broadcasting loop
    # app.add_handler(CallbackQueryHandler(campaign_control, pattern=r"^camp\|"))

    print("Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()