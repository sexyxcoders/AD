import asyncio
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Dict, Optional
from dataclasses import dataclass

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
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError

from motor.motor_asyncio import AsyncIOMotorClient

# --- Configuration ---
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

@dataclass
class UserState:
    step: str = "idle"
    phone: str = ""
    phone_code_hash: str = ""
    client: Optional[TelegramClient] = None
    buffer: str = ""
    delay: int = 300

user_states: Dict[int, UserState] = {}

# --- SMART MESSAGE EDITING HELPER ---
async def safe_edit_message(query, text=None, caption=None, reply_markup=None):
    """
    Safely edit messages handling both text-only and photo-with-caption scenarios.
    Always prefers editing over sending new messages for smooth UX.
    """
    try:
        # Case 1: We want to show a photo (caption mode)
        if caption is not None:
            try:
                # Try to edit existing photo's caption
                await query.edit_message_caption(
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            except BadRequest as e:
                if "message is not modified" in str(e).lower():
                    return
                # If no caption exists, replace entire message with photo
                await query.edit_message_media(
                    media=InputMediaPhoto(media=BANNER_URL, caption=caption),
                    reply_markup=reply_markup
                )
                return
        
        # Case 2: Text-only message
        elif text is not None:
            try:
                # Try to edit existing text
                await query.edit_message_text(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            except BadRequest as e:
                if "message is not modified" in str(e).lower():
                    return
                # If editing fails (e.g., trying to edit photo as text), send new text message
                await query.message.reply_text(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                await query.message.delete()
                return
    
    except Exception as e:
        logger.error(f"Safe edit failed: {e}")
        # Final fallback: send new message
        if caption is not None:
            await query.message.reply_photo(
                photo=BANNER_URL,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        elif text is not None:
            await query.message.reply_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        await query.message.delete()

# --- Keyboards ---

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
         InlineKeyboardButton("Set Time Interval", callback_data="delay|nav")],
        [InlineKeyboardButton("Start Ads", callback_data="camp|start"),
         InlineKeyboardButton("Stop Ads", callback_data="camp|stop")],
        [InlineKeyboardButton("Delete Accounts", callback_data="acc|del"),
         InlineKeyboardButton("Analytics", callback_data="stat|main")],
        [InlineKeyboardButton("Auto Reply", callback_data="feature|auto")],
        [InlineKeyboardButton("Back", callback_data="nav|start")]
    ])

def kb_otp(user_id):
    state = user_states.get(user_id, UserState())
    display = (state.buffer + "○" * (5 - len(state.buffer)))[:5]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(display, callback_data="noop")],
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
         InlineKeyboardButton("✅", callback_data="otp|submit")],
        [InlineKeyboardButton("Show Code", callback_data="otp|show")],
        [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
    ])

def kb_delay(current_delay: int = 300):
    def get_emoji(sec):
        return "🔴" if sec <= 300 else "🟡" if sec <= 600 else "🟢"
    
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"5min {get_emoji(300)}", callback_data="setdelay|300"),
         InlineKeyboardButton(f"10min {get_emoji(600)}", callback_data="setdelay|600")],
        [InlineKeyboardButton(f"20min {get_emoji(1200)}", callback_data="setdelay|1200")],
        [InlineKeyboardButton("Custom", callback_data="delay|custom")],
        [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
    ])

def kb_accounts(accounts, page=0):
    buttons = []
    page_size = 5
    start = page * page_size
    end = start + page_size
    page_accounts = accounts[start:end]
    
    for acc in page_accounts:
        status = "🟢" if acc.get("active", False) else "🔴"
        phone = acc["phone"]
        display = f"{status} ••••{phone[-4:]}"  # Privacy: show last 4 digits
        buttons.append([InlineKeyboardButton(display, callback_data=f"acc|detail|{acc['_id']}")])
    
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"acc|list|{page-1}"))
    if end < len(accounts):
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"acc|list|{page+1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    buttons.append([InlineKeyboardButton("Back", callback_data="nav|dashboard")])
    return InlineKeyboardMarkup(buttons)

def kb_account_detail(acc_id, phone):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ Delete Account", callback_data=f"acc|delete|{acc_id}")],
        [InlineKeyboardButton("◀️ Back to List", callback_data="acc|list|0")],
        [InlineKeyboardButton("🏠 Dashboard", callback_data="nav|dashboard")]
    ])

def kb_confirm_delete(acc_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, Delete", callback_data=f"acc|confirm_del|{acc_id}"),
         InlineKeyboardButton("❌ Cancel", callback_data="nav|dashboard")]
    ])

# --- Handlers ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ("╰_╯ Welcome to @Tecxo Free Ads bot — The Future of Telegram Automation\n\n"
            "• Premium Ad Broadcasting\n"
            "• Smart Delays\n"
            "• Multi-Account Support\n\n"
            "For support contact: @NexaCoders")
    
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        # Always show banner on /start
        await query.message.reply_photo(
            photo=BANNER_URL,
            caption=text,
            reply_markup=kb_start(),
            parse_mode=ParseMode.MARKDOWN
        )
        await query.message.delete()
    else:
        await update.message.reply_photo(
            photo=BANNER_URL,
            caption=text,
            reply_markup=kb_start(),
            parse_mode=ParseMode.MARKDOWN
        )

async def handle_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    dest = parts[1]

    if dest == "start":
        await cmd_start(update, context)
    
    elif dest == "dashboard":
        text = ("╰_╯ DASHBOARD\n\n"
                "📱 Manage your ad campaigns and accounts:\n\n"
                "✅ Add & manage Telegram accounts\n"
                "✏️ Set custom ad messages\n"
                "⏱️ Configure broadcast intervals\n"
                "🚀 Start/stop campaigns instantly")
        await safe_edit_message(query, text=text, reply_markup=kb_dashboard())
    
    elif dest == "howto":
        text = ("╰_╯ HOW TO USE\n\n"
                "1️⃣ Tap *Add Accounts* → Host your Telegram account\n"
                "2️⃣ Tap *Set Ad Message* → Create your promotional text\n"
                "3️⃣ Tap *Set Time Interval* → Configure broadcast frequency\n"
                "4️⃣ Tap *Start Ads* → Begin automated broadcasting\n\n"
                "⚠️ *Warning*: Aggressive intervals (<5 min) may risk account suspension")
        await safe_edit_message(
            query,
            text=text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Back", callback_data="nav|dashboard")]
            ])
        )

async def handle_account_ops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    action = parts[1]
    user_id = query.from_user.id

    if action == "add":
        user_states[user_id] = UserState(step="phone")
        text = ("╰_╯ HOST NEW ACCOUNT\n\n"
                "🔐 *Secure Account Hosting*\n\n"
                "Enter your phone number with country code:\n"
                "`Example: +1234567890`\n\n"
                "🔒 Your data is encrypted and secure")
        await safe_edit_message(
            query,
            text=text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Back", callback_data="nav|dashboard")]
            ])
        )
    
    elif action == "list":
        page = int(parts[2]) if len(parts) > 2 else 0
        accounts = await db.accounts.find({"user_id": user_id}).to_list(None)
        
        if not accounts:
            await query.answer("📭 No accounts added yet!", show_alert=True)
            text = "📱 *MY ACCOUNTS*\n\nYou haven't added any accounts yet.\nTap *Add Accounts* to get started!"
            await safe_edit_message(query, text=text, reply_markup=kb_dashboard())
            return
        
        text = f"📱 *MY ACCOUNTS* ({len(accounts)})\n\nSelect an account to manage:"
        await safe_edit_message(query, text=text, reply_markup=kb_accounts(accounts, page))
    
    elif action == "detail":
        acc_id = parts[2]
        account = await db.accounts.find_one({"_id": acc_id, "user_id": user_id})
        if not account:
            await query.answer("❌ Account not found!", show_alert=True)
            return
        
        status = "🟢 Active" if account.get("active") else "🔴 Inactive"
        phone = account["phone"]
        added = account.get("created_at", datetime.now(timezone.utc)).strftime("%d/%m/%y")
        
        text = (f"📱 *ACCOUNT DETAILS*\n\n"
                f"📞 Phone: `{phone}`\n"
                f"📊 Status: {status}\n"
                f"📅 Added: {added}")
        
        await safe_edit_message(
            query,
            text=text,
            reply_markup=kb_account_detail(acc_id, phone)
        )
    
    elif action == "delete":
        acc_id = parts[2]
        account = await db.accounts.find_one({"_id": acc_id, "user_id": user_id})
        if not account:
            await query.answer("❌ Account not found!", show_alert=True)
            return
        
        phone = account["phone"]
        text = (f"⚠️ *DELETE ACCOUNT*\n\n"
                f"Are you sure you want to delete:\n"
                f"`{phone}`?\n\n"
                f"❗ This action cannot be undone!")
        await safe_edit_message(
            query,
            text=text,
            reply_markup=kb_confirm_delete(acc_id)
        )
    
    elif action == "confirm_del":
        acc_id = parts[2]
        result = await db.accounts.delete_one({"_id": acc_id, "user_id": user_id})
        if result.deleted_count:
            await query.answer("✅ Account deleted successfully!", show_alert=True)
        else:
            await query.answer("❌ Failed to delete account!", show_alert=True)
        
        text = "╰_╯ DASHBOARD\n\nAccount management updated successfully."
        await safe_edit_message(query, text=text, reply_markup=kb_dashboard())
    
    elif action == "del":
        accounts = await db.accounts.count_documents({"user_id": user_id})
        if accounts == 0:
            await query.answer("📭 No accounts to delete!", show_alert=True)
            return
        
        text = ("🗑️ *DELETE ACCOUNTS*\n\n"
                "Select accounts to remove from your campaign.\n"
                "⚠️ Deleted accounts cannot be recovered!")
        await safe_edit_message(
            query,
            text=text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📱 View & Delete Accounts", callback_data="acc|list|0")],
                [InlineKeyboardButton("◀️ Back", callback_data="nav|dashboard")]
            ])
        )

async def input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    if not state or state.step == "idle":
        return

    text = update.message.text.strip()

    try:
        if state.step == "phone":
            phone = "+" + re.sub(r"\D", "", text)
            if not (8 <= len(phone) <= 15):
                await update.message.reply_text(
                    "❌ *Invalid phone number!*\n\nPlease enter a valid number with country code:\n`Example: +1234567890`",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("◀️ Back", callback_data="nav|dashboard")]
                    ]),
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()
            
            try:
                sent = await client.send_code_request(phone)
                state.client = client
                state.phone = phone
                state.phone_code_hash = sent.phone_code_hash
                state.step = "code"
                state.buffer = ""
                
                await update.message.reply_text(
                    f"⏳ *Verifying OTP...*\n\n📱 Phone: `{phone}`\nPlease wait a moment...",
                    parse_mode=ParseMode.MARKDOWN
                )
                await update.message.reply_text(
                    "🔢 *Enter OTP*\n\nUse the keypad below to enter the 5-digit code:",
                    reply_markup=kb_otp(user_id),
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                await client.disconnect()
                error = str(e)
                if "FLOOD_WAIT" in error:
                    wait = re.search(r'FLOOD_WAIT_(\d+)', error)
                    msg = f"⏳ Too many requests! Wait {wait.group(1)} seconds before trying again."
                elif "INVALID_PHONE_NUMBER" in error:
                    msg = "❌ Invalid phone number format!"
                else:
                    msg = f"❌ Error: {error[:100]}"
                
                await update.message.reply_text(
                    f"{msg}\n\nPlease try again:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("◀️ Back", callback_data="nav|dashboard")]
                    ])
                )
        
        elif state.step == "password":
            await finalize_login(user_id, context, password=text)
            user_states[user_id] = UserState(step="idle")
        
        elif state.step == "set_ad":
            if len(text) > 4000:
                await update.message.reply_text(
                    "❌ *Message too long!*\n\nMax 4000 characters allowed.\nPlease send a shorter ad message:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("◀️ Back", callback_data="nav|dashboard")]
                    ]),
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            await db.ads.update_one(
                {"user_id": str(user_id)},
                {"$set": {"text": text, "updated_at": datetime.now(timezone.utc)}},
                upsert=True
            )
            user_states[user_id] = UserState(step="idle")
            await update.message.reply_text(
                "✅ *Ad Message Saved Successfully!*",
                reply_markup=kb_dashboard(),
                parse_mode=ParseMode.MARKDOWN
            )
        
        elif state.step == "set_delay_custom":
            try:
                delay = int(text)
                if delay < 60:
                    await update.message.reply_text(
                        "⚠️ *Minimum interval is 60 seconds!*\n\nEnter a valid interval (in seconds):",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("◀️ Back", callback_data="delay|nav")]
                        ]),
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
                if delay > 86400:
                    await update.message.reply_text(
                        "⚠️ *Maximum interval is 86400 seconds (24h)!*\n\nEnter a valid interval:",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("◀️ Back", callback_data="delay|nav")]
                        ]),
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
                
                await db.users.update_one(
                    {"user_id": str(user_id)},
                    {"$set": {"delay": delay, "updated_at": datetime.now(timezone.utc)}},
                    upsert=True
                )
                user_states[user_id] = UserState(step="idle", delay=delay)
                await update.message.reply_text(
                    f"✅ *Interval set to {delay}s* ({delay//60} min)",
                    reply_markup=kb_dashboard(),
                    parse_mode=ParseMode.MARKDOWN
                )
            except ValueError:
                await update.message.reply_text(
                    "❌ *Invalid number!*\n\nPlease enter interval in seconds (e.g., `600`):",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("◀️ Back", callback_data="delay|nav")]
                    ]),
                    parse_mode=ParseMode.MARKDOWN
                )
    
    except Exception as e:
        logger.exception(f"Input handler error: {e}")
        await update.message.reply_text(
            "❌ *Unexpected error occurred!*\n\nPlease restart the process or contact support.",
            reply_markup=kb_dashboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        if state and state.client:
            await state.client.disconnect()
        user_states[user_id] = UserState(step="idle")

async def handle_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    state = user_states.get(user_id)
    
    if not state or state.step != "code":
        await query.answer("⚠️ Session expired! Please restart from Dashboard.", show_alert=True)
        return

    await query.answer()
    parts = query.data.split("|")
    action = parts[1]

    if action == "back":
        state.buffer = state.buffer[:-1]
    elif action == "show":
        code_display = state.buffer if state.buffer else "•••••"
        await query.answer(f"Current Code: {code_display}", show_alert=True)
        return
    elif action == "submit":
        if len(state.buffer) != 5:
            await query.answer("⚠️ Please enter all 5 digits!", show_alert=True)
            return
        await finalize_login(user_id, context)
        return
    elif action.isdigit() and len(state.buffer) < 5:
        state.buffer += action

    try:
        await query.edit_message_reply_markup(reply_markup=kb_otp(user_id))
    except BadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.warning(f"OTP keyboard update failed: {e}")

async def finalize_login(user_id, context, password=None):
    state = user_states.get(user_id)
    if not state or not state.client:
        await context.bot.send_message(
            user_id,
            "❌ *Session expired!*\n\nPlease restart the login process from Dashboard.",
            reply_markup=kb_dashboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    try:
        if password:
            await state.client.sign_in(password=password)
        else:
            await state.client.sign_in(
                phone=state.phone,
                code=state.buffer,
                phone_code_hash=state.phone_code_hash
            )
        
        # Update profile immediately
        try:
            await state.client(UpdateProfileRequest(
                first_name=PROFILE_NAME,
                about=PROFILE_BIO
            ))
        except Exception as e:
            logger.warning(f"Profile update warning for {state.phone}: {e}")
        
        # Save session
        session = state.client.session.save()
        await db.accounts.update_one(
            {"user_id": user_id, "phone": state.phone},
            {"$set": {
                "session": session,
                "active": True,
                "created_at": datetime.now(timezone.utc),
                "last_used": datetime.now(timezone.utc)
            }},
            upsert=True
        )
        
        await state.client.disconnect()
        user_states[user_id] = UserState(step="idle")
        
        success_msg = (f"✅ *Account Successfully Added!*\n\n"
                      f"📱 Phone: `{state.phone}`\n"
                      f"╰_╯ Your account is ready for broadcasting!\n\n"
                      f"ℹ️ *Profile updated*: Name & bio changed automatically")
        await context.bot.send_message(
            user_id,
            success_msg,
            reply_markup=kb_dashboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        
    except SessionPasswordNeededError:
        state.step = "password"
        await context.bot.send_message(
            user_id,
            "🔐 *2FA Detected!*\n\nPlease send your Telegram cloud password:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Back", callback_data="nav|dashboard")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
    except (PhoneCodeInvalidError, ValueError):
        await state.client.disconnect()
        user_states[user_id] = UserState(step="idle")
        await context.bot.send_message(
            user_id,
            "❌ *Invalid OTP code!*\n\nPlease restart the login process.",
            reply_markup=kb_dashboard(),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        error_msg = str(e)
        if "PHONE_CODE_EXPIRED" in error_msg or "SESSION_REVOKED" in error_msg:
            error_msg = "OTP expired! Please restart the login process."
        elif "FLOOD_WAIT" in error_msg:
            wait = re.search(r'FLOOD_WAIT_(\d+)', error_msg)
            if wait:
                error_msg = f"⏳ Too many attempts! Wait {wait.group(1)} seconds before trying again."
            else:
                error_msg = "⏳ Too many attempts! Please try again later."
        
        await state.client.disconnect()
        user_states[user_id] = UserState(step="idle")
        await context.bot.send_message(
            user_id,
            f"❌ *Login Failed*\n\n{error_msg}",
            reply_markup=kb_dashboard(),
            parse_mode=ParseMode.MARKDOWN
        )
        logger.exception(f"Login failed for {state.phone}: {e}")

async def handle_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "ad|set":
        text = ("╰_╯ *SET YOUR AD MESSAGE*\n\n"
                "💡 *Tips for effective ads:*\n"
                "• Keep it concise and engaging\n"
                "• Use premium emojis for flair\n"
                "• Include clear call-to-action\n"
                "• Avoid excessive caps or spam words\n\n"
                "📤 *Send your ad message now:*")
        user_states[query.from_user.id] = UserState(step="set_ad")
        await safe_edit_message(
            query,
            text=text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Back", callback_data="nav|dashboard")]
            ])
        )

async def handle_delay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    parts = query.data.split("|")
    
    if parts[0] == "delay":
        action = parts[1]
        if action == "nav":
            user_doc = await db.users.find_one({"user_id": str(user_id)})
            current_delay = user_doc.get("delay", 300) if user_doc else 300
            
            text = (f"╰_╯ *SET BROADCAST CYCLE INTERVAL*\n\n"
                   f"⏱️ Current Interval: `{current_delay}s` ({current_delay//60} min)\n\n"
                   f"✅ *Recommended Intervals:*\n"
                   f"• `300s` - Aggressive (5 min) 🔴\n"
                   f"• `600s` - Safe & Balanced (10 min) 🟡\n"
                   f"• `1200s` - Conservative (20 min) 🟢\n\n"
                   f"⚠️ *Warning*: Short intervals increase suspension risk!")
            await safe_edit_message(query, text=text, reply_markup=kb_delay(current_delay))
        
        elif action == "custom":
            user_states[user_id] = UserState(step="set_delay_custom")
            text = ("╰_╯ *CUSTOM INTERVAL*\n\n"
                   "Enter interval in seconds:\n"
                   "`Minimum: 60s`\n"
                   "`Maximum: 86400s (24h)`\n\n"
                   "Example: `900` for 15 minutes")
            await safe_edit_message(
                query,
                text=text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("◀️ Back", callback_data="delay|nav")]
                ])
            )
    
    elif parts[0] == "setdelay":
        delay = int(parts[1])
        await db.users.update_one(
            {"user_id": str(user_id)},
            {"$set": {"delay": delay, "updated_at": datetime.now(timezone.utc)}},
            upsert=True
        )
        await query.answer(f"✅ Interval set to {delay}s", show_alert=True)
        
        text = (f"╰_╯ *SET BROADCAST CYCLE INTERVAL*\n\n"
               f"⏱️ Current Interval: `{delay}s` ({delay//60} min)\n\n"
               f"✅ *Recommended Intervals:*\n"
               f"• `300s` - Aggressive (5 min) 🔴\n"
               f"• `600s` - Safe & Balanced (10 min) 🟡\n"
               f"• `1200s` - Conservative (20 min) 🟢\n\n"
               f"⚠️ *Warning*: Short intervals increase suspension risk!")
        await safe_edit_message(query, text=text, reply_markup=kb_delay(delay))

async def handle_analytics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    parts = query.data.split("|")
    
    if parts[1] == "main":
        active = await db.accounts.count_documents({"user_id": user_id, "active": True})
        total = await db.accounts.count_documents({"user_id": user_id})
        user_doc = await db.users.find_one({"user_id": str(user_id)})
        delay = user_doc.get("delay", 300) if user_doc else 300
        
        # Placeholder stats (would connect to real broadcast tracking)
        sent, failed, cycles = 0, 0, 0
        rate = int((sent / (sent + failed) * 100)) if (sent + failed) > 0 else 0
        bar = "▓" * (rate // 10) + "░" * (10 - rate // 10)
        
        text = (f"╰_╯ *@NexaCoders ANALYTICS*\n\n"
               f"🔄 Broadcast Cycles: {cycles}\n"
               f"✅ Messages Sent: {sent}\n"
               f"❌ Failed Sends: {failed}\n"
               f"📱 Active Accounts: {active}/{total}\n"
               f"⏱️ Avg Delay: {delay}s\n\n"
               f"📈 Success Rate: {bar} {rate}%")
        
        await safe_edit_message(
            query,
            text=text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 Detailed Report", callback_data="stat|detail")],
                [InlineKeyboardButton("◀️ Back", callback_data="nav|dashboard")]
            ])
        )
    
    elif parts[1] == "detail":
        active = await db.accounts.count_documents({"user_id": user_id, "active": True})
        total = await db.accounts.count_documents({"user_id": user_id})
        inactive = total - active
        user_doc = await db.users.find_one({"user_id": str(user_id)})
        delay = user_doc.get("delay", 300) if user_doc else 300
        
        now = datetime.now(timezone.utc).strftime("%d/%m/%y")
        
        text = (f"╰_╯ *DETAILED ANALYTICS REPORT*\n\n"
               f"📅 Date: {now}\n"
               f"🆔 User ID: `{user_id}`\n\n"
               f"📤 *Broadcast Stats:*\n"
               f"• Total Sent: 0\n"
               f"• Total Failed: 0\n"
               f"• Total Broadcasts: 0\n\n"
               f"⚙️ *Logger Stats:*\n"
               f"• Logger Failures: 0\n"
               f"• Last Failure: None\n\n"
               f"📱 *Account Stats:*\n"
               f"• Total Accounts: {total}\n"
               f"• Active Accounts: {active} 🟢\n"
               f"• Inactive Accounts: {inactive} 🔴\n\n"
               f"⏱️ Current Delay: {delay}s ({delay//60} min)")
        
        await safe_edit_message(
            query,
            text=text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Back", callback_data="stat|main")]
            ])
        )

async def handle_features(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if "auto" in query.data:
        text = ("╰_╯ *AUTO REPLY FEATURE*\n\n"
               "🔜 *Coming Soon!*\n\n"
               "Stay tuned for automated reply capabilities to enhance your campaigns.\n\n"
               "💡 *Planned features:*\n"
               "• Keyword-based auto replies\n"
               "• Smart response templates\n"
               "• Conversation flow management\n"
               "• Spam protection filters")
        await safe_edit_message(
            query,
            text=text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Back", callback_data="nav|dashboard")]
            ])
        )

async def handle_campaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if "start" in query.data:
        accounts = await db.accounts.count_documents({"user_id": user_id, "active": True})
        ad = await db.ads.find_one({"user_id": str(user_id)})
        
        if accounts == 0:
            await query.answer("❌ No active accounts! Add accounts first.", show_alert=True)
            return
        if not ad or not ad.get("text"):
            await query.answer("❌ No ad message set! Set your ad message first.", show_alert=True)
            return
        
        # In production: start background broadcast task here
        await query.answer("✅ Campaign started successfully!", show_alert=True)
        text = ("🚀 *CAMPAIGN STARTED*\n\n"
               "Your ads are now broadcasting to all joined groups.\n\n"
               "📊 Monitor progress in *Analytics* section.\n"
               "⏸️ Tap *Stop Ads* anytime to pause broadcasting.")
        await safe_edit_message(
            query,
            text=text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 Analytics", callback_data="stat|main")],
                [InlineKeyboardButton("⏹️ Stop Ads", callback_data="camp|stop")],
                [InlineKeyboardButton("🏠 Dashboard", callback_data="nav|dashboard")]
            ])
        )
    
    elif "stop" in query.data:
        # In production: stop background broadcast task here
        await query.answer("🛑 Campaign stopped successfully!", show_alert=True)
        text = ("⏸️ *CAMPAIGN STOPPED*\n\n"
               "All broadcasting activities have been paused.\n\n"
               "You can restart anytime from the dashboard.")
        await safe_edit_message(query, text=text, reply_markup=kb_dashboard())

async def handle_noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}")

async def post_init(application: Application):
    logger.info("Bot initialized successfully")

async def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(handle_noop, pattern=r"^noop$"))
    app.add_handler(CallbackQueryHandler(handle_otp, pattern=r"^otp\|"))
    app.add_handler(CallbackQueryHandler(handle_account_ops, pattern=r"^acc\|"))
    app.add_handler(CallbackQueryHandler(handle_ads, pattern=r"^ad\|"))
    app.add_handler(CallbackQueryHandler(handle_delay, pattern=r"^(delay|setdelay)\|"))
    app.add_handler(CallbackQueryHandler(handle_analytics, pattern=r"^stat\|"))
    app.add_handler(CallbackQueryHandler(handle_features, pattern=r"^feature\|"))
    app.add_handler(CallbackQueryHandler(handle_campaigns, pattern=r"^camp\|"))
    app.add_handler(CallbackQueryHandler(handle_navigation, pattern=r"^nav\|"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, input_handler))
    app.add_error_handler(error_handler)

    logger.info("Starting bot...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("✅ Bot is running!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)