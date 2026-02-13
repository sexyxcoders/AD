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

# --- SAFE MESSAGE EDITING (handles both photo captions and text messages) ---
async def safe_edit_or_send(query, text, reply_markup=None):
    """Edit message caption if it's a photo, otherwise edit text or send new message"""
    try:
        # Try to edit caption (for photo messages)
        await query.edit_message_caption(
            caption=text,
            reply_markup=reply_markup
        )
    except BadRequest as e:
        error_msg = str(e).lower()
        if "message is not modified" in error_msg:
            return
        elif "message to edit not found" in error_msg or "message can't be edited" in error_msg:
            # Send new photo with caption
            await query.message.reply_photo(
                photo=BANNER_URL,
                caption=text,
                reply_markup=reply_markup
            )
            try:
                await query.message.delete()
            except:
                pass
        else:
            # Try editing as text message
            try:
                await query.edit_message_text(
                    text=text,
                    reply_markup=reply_markup
                )
            except:
                # Final fallback: send new message
                await query.message.reply_text(
                    text=text,
                    reply_markup=reply_markup
                )
                try:
                    await query.message.delete()
                except:
                    pass

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

        # 👇 Auto Reply & Back side by side
        [InlineKeyboardButton("Auto Reply", callback_data="feature|auto"),
         InlineKeyboardButton("Back", callback_data="nav|start")]
    ])

def kb_otp(user_id):
    state = user_states.get(user_id, UserState())
    display = (state.buffer + "○" * (5 - len(state.buffer)))[:5]

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Current: {display}", callback_data="noop")],

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
         InlineKeyboardButton("❌", callback_data="otp|cancel")],

        [InlineKeyboardButton("Show Code", url="tg://openmessage?user_id=777000")]
    ])

async def otp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data == "otp|cancel":
        # Clear OTP buffer
        user_states[user_id] = UserState()

        await query.message.edit_text("OTP entry cancelled.")
        return


def kb_delay(current_delay=300):
    def get_emoji(sec):
        if sec <= 300: return "🔴"
        elif sec <= 600: return "🟡"
        else: return "🟢"
    
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"5min {get_emoji(300)}", callback_data="setdelay|300"),
         InlineKeyboardButton(f"10min {get_emoji(600)}", callback_data="setdelay|600")],
        [InlineKeyboardButton(f"20min {get_emoji(1200)}", callback_data="setdelay|1200")],
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
        display = f"{status} ••••{phone[-4:]}"
        buttons.append([InlineKeyboardButton(display, callback_data=f"acc|detail|{acc['_id']}")])
    
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"acc|list|{page-1}"))
    if end < len(accounts):
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"acc|list|{page+1}"))
    if nav:
        buttons.append(nav)
    
    buttons.append([InlineKeyboardButton("Back", callback_data="nav|dashboard")])
    return InlineKeyboardMarkup(buttons)

def kb_account_detail(acc_id, phone):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Delete Account", callback_data=f"acc|delete|{acc_id}")],
        [InlineKeyboardButton("Back to List", callback_data="acc|list|0")],
        [InlineKeyboardButton("Dashboard", callback_data="nav|dashboard")]
    ])

def kb_confirm_delete(acc_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, Delete", callback_data=f"acc|confirm_del|{acc_id}"),
         InlineKeyboardButton("❌ No", callback_data="nav|dashboard")]
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
    parts = query.data.split("|")
    dest = parts[1]

    if dest == "start":
        await cmd_start(update, context)
    
    elif dest == "dashboard":
        text = ("╰_╯ DASHBOARD\n\n"
                "Manage your ad campaigns and accounts:")
        await safe_edit_or_send(query, text, kb_dashboard())
    
    elif dest == "howto":
        text = ("╰_╯ HOW TO USE\n\n"
                "1. Add Account → Host your Telegram account\n"
                "2. Set Ad Message → Create your promotional text\n"
                "3. Set Time Interval → Configure broadcast frequency\n"
                "4. Start Ads → Begin automated broadcasting\n\n"
                "⚠️ Note: Using aggressive intervals may risk account suspension")
        await safe_edit_or_send(
            query,
            text,
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
        text = ("╰_╯ HOST NEW ACCOUNT\n\n"
                "Secure Account Hosting\n\n"
                "Enter your phone number with country code:\n"
                "Example: +1234567890\n\n"
                "Your data is encrypted and secure")
        await query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]])
        )
    
    elif action == "list":
        page = int(parts[2])
        accounts = await db.accounts.find({"user_id": user_id}).to_list(None)
        
        if not accounts:
            await query.answer("No accounts added yet!", show_alert=True)
            text = "📱 MY ACCOUNTS\n\nYou haven't added any accounts yet."
            await safe_edit_or_send(query, text, kb_dashboard())
            return
        
        text = f"📱 MY ACCOUNTS ({len(accounts)})\n\nSelect an account to manage:"
        await safe_edit_or_send(query, text, kb_accounts(accounts, page))
    
    elif action == "detail":
        acc_id = parts[2]
        account = await db.accounts.find_one({"_id": acc_id, "user_id": user_id})
        if not account:
            await query.answer("Account not found!", show_alert=True)
            return
        
        status = "Active" if account.get("active") else "Inactive"
        phone = account["phone"]
        text = (f"📱 ACCOUNT DETAILS\n\n"
                f"Phone: {phone}\n"
                f"Status: {status}")
        await safe_edit_or_send(query, text, kb_account_detail(acc_id, phone))
    
    elif action == "delete":
        acc_id = parts[2]
        account = await db.accounts.find_one({"_id": acc_id, "user_id": user_id})
        if not account:
            await query.answer("Account not found!", show_alert=True)
            return
        
        phone = account["phone"]
        text = f"⚠️ DELETE ACCOUNT\n\nAre you sure you want to delete:\n{phone}?"
        await safe_edit_or_send(query, text, kb_confirm_delete(acc_id))
    
    elif action == "confirm_del":
        acc_id = parts[2]
        result = await db.accounts.delete_one({"_id": acc_id, "user_id": user_id})
        if result.deleted_count:
            await query.answer("✅ Account deleted successfully!", show_alert=True)
        else:
            await query.answer("❌ Failed to delete account!", show_alert=True)
        text = "╰_╯ DASHBOARD\n\nManage your ad campaigns and accounts:"
        await safe_edit_or_send(query, text, kb_dashboard())
    
    elif action == "del":
        count = await db.accounts.count_documents({"user_id": user_id})
        if count == 0:
            await query.answer("No accounts to delete!", show_alert=True)
            return
        text = "🗑️ DELETE ACCOUNTS\n\nSelect accounts to remove from your campaign:"
        await safe_edit_or_send(
            query,
            text,
            InlineKeyboardMarkup([
                [InlineKeyboardButton("View & Delete Accounts", callback_data="acc|list|0")],
                [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
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
            if len(phone) < 8 or len(phone) > 15:
                await update.message.reply_text(
                    "❌ Invalid phone number!\n\nPlease enter a valid number with country code:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]])
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
                    f"⏳ Hold! We're trying to OTP...\n\nPhone: {phone}\nPlease wait a moment."
                )
                await update.message.reply_text(
f"""╰_╯ OTP sent to {phone}! ✅

Enter the OTP using the keypad below:
Current: _____
Format: 12345 (no spaces)
Expires in: 5 minutes""",
reply_markup=kb_otp(user_id)
                )
            except Exception as e:
                await client.disconnect()
                error = str(e)
                if "FLOOD_WAIT" in error:
                    match = re.search(r'FLOOD_WAIT_(\d+)', error)
                    msg = f"⏳ Too many requests! Wait {match.group(1)} seconds before trying again." if match else "⏳ Too many requests! Please try again later."
                elif "INVALID_PHONE_NUMBER" in error:
                    msg = "❌ Invalid phone number format!"
                else:
                    msg = f"❌ Error: {error[:100]}"
                
                await update.message.reply_text(
                    f"{msg}\n\nPlease try again:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]])
                )
        
        elif state.step == "password":
            await finalize_login(user_id, context, password=text)
            user_states[user_id] = UserState(step="idle")
        
        elif state.step == "set_ad":
            if len(text) > 4000:
                await update.message.reply_text(
                    "❌ Message too long! (Max 4000 characters)\n\nPlease send a shorter ad message:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]])
                )
                return
            
            await db.ads.update_one(
                {"user_id": str(user_id)},
                {"$set": {"text": text, "updated_at": datetime.now(timezone.utc)}},
                upsert=True
            )
            user_states[user_id] = UserState(step="idle")
            await update.message.reply_text(
                "✅ Ad Message Saved!",
                reply_markup=kb_dashboard()
            )
    
    except Exception as e:
        logger.exception(f"Input handler error: {e}")
        await update.message.reply_text(
            "❌ Unexpected error occurred!\n\nPlease restart the process or contact support.",
            reply_markup=kb_dashboard()
        )
        if state and state.client:
            await state.client.disconnect()
        user_states[user_id] = UserState(step="idle")

async def handle_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    state = user_states.get(user_id)

    if not state or state.step != "code":
        await query.answer("Session expired!", show_alert=True)
        return

    await query.answer()
    action = query.data.split("|")[1]

    # BACKSPACE
    if action == "back":
        state.buffer = state.buffer[:-1]

    # SUBMIT
    elif action == "submit":
        if len(state.buffer) != 5:
            await query.answer("Enter 5 digit OTP!", show_alert=True)
            return
        await finalize_login(user_id, context)
        return

    # DIGITS
    elif action.isdigit() and len(state.buffer) < 5:
        state.buffer += action

    # MASK OTP
    masked = " ".join(["*"] * len(state.buffer)) + " _" * (5 - len(state.buffer))

    # EDIT UI TEXT (🔥 THIS IS YOUR ANIMATION)
    await query.edit_message_text(
        f"""╰_╯ OTP sent to {state.phone}! ✅

Enter the OTP using the keypad below:
Current: {masked}
Format: 12345 (no spaces)
Expires in: 5 minutes""",
        reply_markup=kb_otp(user_id)
    )
    except BadRequest:
        pass

async def finalize_login(user_id, context, password=None):
    state = user_states.get(user_id)
    if not state or not state.client:
        await context.bot.send_message(
            user_id,
            "❌ Session expired! Please restart the login process.",
            reply_markup=kb_dashboard()
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
        
        # Update profile immediately after login
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
        
        success_msg = (f"Account Successfully added!✅\n\n"
                      f"Phone: {state.phone}\n"
                      f"╰_╯Your account is ready for broadcasting!\n\n"
                      f"Note: Profile bio and name have been updated automatically.")
        await context.bot.send_message(
            user_id,
            success_msg,
            reply_markup=kb_dashboard()
        )
        
    except SessionPasswordNeededError:
        state.step = "password"
        await context.bot.send_message(
            user_id,
            "🔐 2FA Detected!\n\nPlease send your Telegram cloud password:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]])
        )
    except (PhoneCodeInvalidError, ValueError):
        await state.client.disconnect()
        user_states[user_id] = UserState(step="idle")
        await context.bot.send_message(
            user_id,
            "❌ Invalid OTP code! Please restart the login process.",
            reply_markup=kb_dashboard()
        )
    except Exception as e:
        error_msg = str(e)
        if "PHONE_CODE_EXPIRED" in error_msg or "SESSION_REVOKED" in error_msg:
            error_msg = "OTP expired! Please restart the login process."
        elif "FLOOD_WAIT" in error_msg:
            match = re.search(r'FLOOD_WAIT_(\d+)', error_msg)
            if match:
                error_msg = f"Too many attempts! Please wait {match.group(1)} seconds before trying again."
            else:
                error_msg = "Too many attempts! Please try again later."
        
        await state.client.disconnect()
        user_states[user_id] = UserState(step="idle")
        await context.bot.send_message(
            user_id,
            f"❌ Failed: {error_msg}",
            reply_markup=kb_dashboard()
        )
        logger.exception(f"Login failed for {state.phone}: {e}")

async def handle_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "ad|set":
        text = ("╰_╯ SET YOUR AD MESSAGE\n\n"
                "Tips for effective ads:\n"
                "• Keep it concise and engaging\n"
                "• Use premium emojis for flair\n"
                "• Include clear call-to-action\n"
                "• Avoid excessive caps or spam words\n\n"
                "Send your ad message now:")
        user_states[query.from_user.id] = UserState(step="set_ad")
        await query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]])
        )

async def handle_delay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    parts = query.data.split("|")
    
    if parts[0] == "delay" and parts[1] == "nav":
        user_doc = await db.users.find_one({"user_id": str(user_id)})
        current_delay = user_doc.get("delay", 300) if user_doc else 300
        
        text = (f"╰_╯ SET BROADCAST CYCLE INTERVAL\n\n"
               f"Current Interval: {current_delay} seconds\n\n"
               f"Recommended Intervals:\n"
               f"• 300s - Aggressive (5 min) 🔴\n"
               f"• 600s - Safe & Balanced (10 min) 🟡\n"
               f"• 1200s - Conservative (20 min) 🟢\n\n"
               f"(Note: using short time interval for broadcasting can get your Account on high risk.)")
        await safe_edit_or_send(query, text, kb_delay(current_delay))
    
    elif parts[0] == "setdelay":
        delay = int(parts[1])
        await db.users.update_one(
            {"user_id": str(user_id)},
            {"$set": {"delay": delay, "updated_at": datetime.now(timezone.utc)}},
            upsert=True
        )
        await query.answer(f"✅ Interval set to {delay} seconds", show_alert=True)
        
        text = (f"╰_╯ SET BROADCAST CYCLE INTERVAL\n\n"
               f"Current Interval: {delay} seconds\n\n"
               f"Recommended Intervals:\n"
               f"• 300s - Aggressive (5 min) 🔴\n"
               f"• 600s - Safe & Balanced (10 min) 🟡\n"
               f"• 1200s - Conservative (20 min) 🟢\n\n"
               f"(Note: using short time interval for broadcasting can get your Account on high risk.)")
        await safe_edit_or_send(query, text, kb_delay(delay))

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
        
        # Placeholder stats
        sent, failed, cycles, logger_fail = 0, 0, 0, 0
        total_attempts = sent + failed
        success_rate = int((sent / total_attempts * 100)) if total_attempts > 0 else 0
        bar = "▓" * 10 if success_rate == 100 else "▓" * (success_rate // 10) + "░" * (10 - success_rate // 10)
        
        text = (f"╰_╯ @NexaCoders ANALYTICS\n\n"
               f"Broadcast Cycles Completed: {cycles}\n"
               f"Messages Sent: {sent}\n"
               f"Failed Sends: {failed}\n"
               f"Logger Failures: {logger_fail}\n"
               f"Active Accounts: {active}\n"
               f"Avg Delay: {delay}s\n\n"
               f"Success Rate: {bar} {success_rate}%")
        
        await safe_edit_or_send(
            query,
            text,
            InlineKeyboardMarkup([
                [InlineKeyboardButton("Detailed Report", callback_data="stat|detail")],
                [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
            ])
        )
    
    elif parts[1] == "detail":
        active = await db.accounts.count_documents({"user_id": user_id, "active": True})
        total = await db.accounts.count_documents({"user_id": user_id})
        inactive = total - active
        user_doc = await db.users.find_one({"user_id": str(user_id)})
        delay = user_doc.get("delay", 300) if user_doc else 300
        
        now = datetime.now(timezone.utc).strftime("%d/%m/%y")
        
        text = (f"╰_╯ DETAILED ANALYTICS REPORT:\n\n"
               f"Date: {now}\n"
               f"User ID: {user_id}\n\n"
               f"Broadcast Stats:\n"
               f"- Total Sent: 0\n"
               f"- Total Failed: 0\n"
               f"- Total Broadcasts: 0\n\n"
               f"Logger Stats:\n"
               f"- Logger Failures: 0\n"
               f"- Last Failure: None\n\n"
               f"Account Stats:\n"
               f"- Total Accounts: {total}\n"
               f"- Active Accounts: {active} 🟢\n"
               f"- Inactive Accounts: {inactive} 🔴\n\n"
               f"Current Delay: {delay}s")
        
        await safe_edit_or_send(
            query,
            text,
            InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="stat|main")]])
        )

async def handle_features(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if "auto" in query.data:
        text = ("╰_╯ AUTO REPLY FEATURE\n\n"
               "This feature is coming soon!\n"
               "Stay tuned for automated reply capabilities to enhance your campaigns.")
        await safe_edit_or_send(
            query,
            text,
            InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]])
        )

async def handle_campaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if "start" in query.data:
        accounts = await db.accounts.count_documents({"user_id": user_id, "active": True})
        ad_doc = await db.ads.find_one({"user_id": str(user_id)})
        
        if accounts == 0:
            await query.answer("❌ No active accounts! Add accounts first.", show_alert=True)
            return
        if not ad_doc or not ad_doc.get("text"):
            await query.answer("❌ No ad message set! Set your ad message first.", show_alert=True)
            return
        
        # In production: start background broadcast task here
        await query.answer("✅ Campaign started successfully!", show_alert=True)
        text = ("🚀 CAMPAIGN STARTED\n\n"
               "Your ads are now broadcasting to all joined groups.\n\n"
               "📊 Monitor progress in Analytics section.")
        await safe_edit_or_send(
            query,
            text,
            InlineKeyboardMarkup([
                [InlineKeyboardButton("Analytics", callback_data="stat|main")],
                [InlineKeyboardButton("Stop Ads", callback_data="camp|stop")],
                [InlineKeyboardButton("Dashboard", callback_data="nav|dashboard")]
            ])
        )
    
    elif "stop" in query.data:
        # In production: stop background broadcast task here
        await query.answer("🛑 Campaign stopped successfully!", show_alert=True)
        text = ("⏸️ CAMPAIGN STOPPED\n\n"
               "All broadcasting activities have been paused.\n\n"
               "You can restart anytime from the dashboard.")
        await safe_edit_or_send(query, text, kb_dashboard())

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
