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
campaign_tasks: Dict[int, asyncio.Task] = {}

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

def kb_dashboard(user_id: int):
    accounts_count = await db.accounts.count_documents({"user_id": user_id})
    ad_doc = await db.ads.find_one({"user_id": user_id})
    ad_set = "Set ✅" if ad_doc and ad_doc.get("text") else "Not Set ❌"
    delay_doc = await db.settings.find_one({"user_id": user_id})
    current_delay = delay_doc.get("delay", 300) if delay_doc else 300
    status_doc = await db.campaigns.find_one({"user_id": user_id})
    status = "Running ▶️" if status_doc and status_doc.get("active", False) else "Paused ⏸️"
    
    text = (f"╰_╯ @NexaCoders Ads DASHBOARD\n\n"
            f"•Hosted Accounts: {accounts_count}/5\n"
            f"•Ad Message: {ad_set}\n"
            f"•Cycle Interval: {current_delay}s\n"
            f"•Advertising Status: {status}\n\n"
            f"╰_╯Choose an action below to continue")
    
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Accounts", callback_data="acc|add"),
         InlineKeyboardButton("My Accounts", callback_data="acc|list|0")],

        [InlineKeyboardButton("Set Ad Message", callback_data="ad|set"),
         InlineKeyboardButton("Set Time Interval", callback_data="delay|nav")],

        [InlineKeyboardButton("Start Ads", callback_data="camp|start"),
         InlineKeyboardButton("Stop Ads", callback_data="camp|stop")],

        [InlineKeyboardButton("Delete Accounts", callback_data="acc|del"),
         InlineKeyboardButton("Analytics", callback_data="stat|main")],

        [InlineKeyboardButton("Auto Reply", callback_data="feature|auto"),
         InlineKeyboardButton("Back", callback_data="nav|start")]
    ]), text

def kb_otp(user_id):
    state = user_states.get(user_id, UserState())
    if len(state.buffer) == 5:
        display = "* * * * *"
    else:
        display = (state.buffer + "_" * (5 - len(state.buffer)))[:5]
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
         InlineKeyboardButton("❌ Cancel", callback_data="otp|cancel")],
        [InlineKeyboardButton("Show Code", url="tg://openmessage?user_id=777000")]
    ])

def kb_delay(current_delay=300):
    def get_emoji(sec):
        if sec <= 300: return "🔴"
        elif sec <= 600: return "🟡"
        else: return "🟢"
    
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"5min {get_emoji(300)}", callback_data="setdelay|300"),
         InlineKeyboardButton(f"10min {get_emoji(600)}", callback_data="setdelay|600"),
         InlineKeyboardButton(f"20min {get_emoji(1200)}", callback_data="setdelay|1200")],
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

def kb_detailed_report():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Back", callback_data="stat|main")]
    ])

def kb_auto_reply():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
    ])

# --- Handlers ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.callback_query:
        query = update.callback_query
        await query.answer()
    else:
        query = None
    
    markup, text = kb_dashboard(user_id)
    if query:
        await safe_edit_or_send(query, text, markup)
    else:
        await update.message.reply_photo(
            photo=BANNER_URL,
            caption=text,
            reply_markup=markup
        )

async def handle_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    dest = parts[1]

    if dest == "start":
        await cmd_start(update, context)
        return
    
    elif dest == "dashboard":
        user_id = query.from_user.id
        markup, text = kb_dashboard(user_id)
        await safe_edit_or_send(query, text, markup)
        return
    
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
        text = ("╰_╯HOST NEW ACCOUNT\n\n"
                "Secure Account Hosting\n\n"
                "Enter your phone number with country code:\n"
                "Example: +1234567890\n\n"
                "Your data is encrypted and secure")
        await query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]])
        )
        return
    
    elif action == "list":
        page = int(parts[2])
        accounts = await db.accounts.find({"user_id": user_id}).to_list(None)
        
        if not accounts:
            await query.answer("No accounts added yet!", show_alert=True)
            markup, text = kb_dashboard(user_id)
            await safe_edit_or_send(query, text, markup)
            return
        
        text = f"📱 MY ACCOUNTS ({len(accounts)})\n\nSelect an account to manage:"
        await safe_edit_or_send(query, text, kb_accounts(accounts, page))
        return
    
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
        return
    
    elif action == "delete":
        acc_id = parts[2]
        account = await db.accounts.find_one({"_id": acc_id, "user_id": user_id})
        if not account:
            await query.answer("Account not found!", show_alert=True)
            return
        
        phone = account["phone"]
        text = f"⚠️ DELETE ACCOUNT\n\nAre you sure you want to delete:\n{phone}?"
        await safe_edit_or_send(query, text, kb_confirm_delete(acc_id))
        return
    
    elif action == "confirm_del":
        acc_id = parts[2]
        result = await db.accounts.delete_one({"_id": acc_id, "user_id": user_id})
        if result.deleted_count:
            await query.answer("✅ Account deleted successfully!", show_alert=True)
        else:
            await query.answer("❌ Failed to delete account!", show_alert=True)
        markup, text = kb_dashboard(user_id)
        await safe_edit_or_send(query, text, markup)
        return
    
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
                otp_text = f"╰_╯ OTP sent to {phone}! ✅\n\nEnter the OTP using the keypad below\nCurrent: _____\nFormat: 12345 (no spaces needed)\nValid for: 5 minutes"
                await update.message.reply_text(
                    otp_text,
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
                {"user_id": user_id},
                {"$set": {"text": text, "updated_at": datetime.now(timezone.utc)}},
                upsert=True
            )
            user_states[user_id] = UserState(step="idle")
            await update.message.reply_text(
                "✅ Ad Message Saved!",
                reply_markup=kb_dashboard(user_id)[1]  # Reuse dashboard markup logic
            )
    
        elif state.step == "set_delay_custom":
            try:
                custom_delay = int(text)
                if custom_delay < 60:
                    raise ValueError("Too short")
                await db.settings.update_one(
                    {"user_id": user_id},
                    {"$set": {"delay": custom_delay, "updated_at": datetime.now(timezone.utc)}},
                    upsert=True
                )
                user_states[user_id] = UserState(step="idle")
                await update.message.reply_text(
                    f"✅ Interval set to {custom_delay}s!",
                    reply_markup=kb_dashboard(user_id)[1]
                )
            except ValueError:
                await update.message.reply_text(
                    "❌ Invalid number! Please send a valid seconds value (>=60):",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]])
                )
    
    except Exception as e:
        logger.exception(f"Input handler error: {e}")
        await update.message.reply_text(
            "❌ Unexpected error occurred!\n\nPlease restart the process or contact support.",
            reply_markup=kb_dashboard(user_id)[1]
        )
        if state and state.client:
            await state.client.disconnect()
        user_states[user_id] = UserState(step="idle")

async def handle_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    state = user_states.get(user_id)
    
    if not state or state.step != "code":
        await query.answer("Session expired! Please restart the process.", show_alert=True)
        return

    await query.answer()
    parts = query.data.split("|")
    action = parts[1]

    if action == "cancel":
        user_states[user_id] = UserState()
        await safe_edit_or_send(query, "Process Cancelled.")
        return

    if action == "back":
        state.buffer = state.buffer[:-1] if state.buffer else ""
    elif action.isdigit():
        if len(state.buffer) < 5:
            state.buffer += action
        if len(state.buffer) == 5:
            # Auto-submit on full
            await finalize_login(user_id, context)
            return

    # Update markup
    otp_text = f"╰_╯ OTP sent to {state.phone}! ✅\n\nEnter the OTP using the keypad below\nCurrent: {state.buffer + '_' * (5 - len(state.buffer)) if len(state.buffer) < 5 else '* * * * *'}\nFormat: 12345 (no spaces needed)\nValid for: 5 minutes"
    if len(state.buffer) == 5:
        otp_text += "\n\nVerifying OTP..."
    await safe_edit_or_send(query, otp_text, kb_otp(user_id))

async def finalize_login(user_id, context, password=None):
    state = user_states.get(user_id)
    if not state or not state.client:
        await context.bot.send_message(
            user_id,
            "❌ Session expired! Please restart the login process.",
            reply_markup=kb_dashboard(user_id)[1]
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
                      f"Note: Profile bio and name will be updated during the first broadcast, you change it if you want.")
        await context.bot.send_message(
            user_id,
            success_msg,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Dashboard", callback_data="nav|dashboard")]])
        )
        
    except SessionPasswordNeededError:
        state.step = "password"
        await context.bot.send_message(
            user_id,
            "🔐 2FA Detected!\n\nPlease send your Telegram cloud password:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]])
        )
    except PhoneCodeInvalidError:
        await context.bot.send_message(
            user_id,
            "❌ Invalid OTP! Please restart the process.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]])
        )
    except Exception as e:
        logger.exception(f"Login error: {e}")
        await context.bot.send_message(
            user_id,
            "❌ Login failed! Please try again.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]])
        )

async def handle_ad_ops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    action = parts[1]
    user_id = query.from_user.id

    if action == "set":
        ad_doc = await db.ads.find_one({"user_id": user_id})
        current_ad = ad_doc.get("text", "") if ad_doc else ""
        tips = ("Tips for effective ads:\n"
                "•Keep it concise and engaging\n"
                "•Use premium emojis for flair\n"
                "•Include clear call-to-action\n"
                "•Avoid excessive caps or spam words\n\n"
                "Send your ad message now:")
        text = f"╰_╯ SET YOUR AD MESSAGE\n\n"
        if current_ad:
            text += f"Current Ad Message: {current_ad}\n\n"
        text += tips
        user_states[user_id] = UserState(step="set_ad")
        await safe_edit_or_send(query, text, InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="nav|dashboard")]]))

async def handle_delay_ops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    action = parts[1]
    user_id = query.from_user.id

    if action == "nav":
        delay_doc = await db.settings.find_one({"user_id": user_id})
        current_delay = delay_doc.get("delay", 300) if delay_doc else 300
        text = (f"╰_╯SET BROADCAST CYCLE INTERVAL\n\n"
                f"Current Interval: {current_delay} seconds\n\n"
                f"Recommended Intervals:\n"
                f"•300s - Aggressive (5 min) 🔴\n"
                f"•600s - Safe & Balanced (10 min) 🟡\n"
                f"•1200s - Conservative (20 min) 🟢\n\n"
                f"To set custom time interval Send a number (in seconds):\n\n"
                f"(Note: using short time interval for broadcasting can get your Account on high risk.)")
        await safe_edit_or_send(query, text, kb_delay(current_delay))
        return
    
    elif action == "set":
        new_delay = int(parts[2])
        await db.settings.update_one(
            {"user_id": user_id},
            {"$set": {"delay": new_delay, "updated_at": datetime.now(timezone.utc)}},
            upsert=True
        )
        await query.answer(f"✅ Interval set to {new_delay}s!", show_alert=True)
        markup, text = kb_dashboard(user_id)
        await safe_edit_or_send(query, text, markup)

async def handle_campaign_ops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    action = parts[1]
    user_id = query.from_user.id

    accounts_count = await db.accounts.count_documents({"user_id": user_id, "active": True})
    ad_doc = await db.ads.find_one({"user_id": user_id})

    if action == "start":
        if accounts_count == 0:
            await query.answer("No active accounts! Add some first.", show_alert=True)
            return
        if not ad_doc or not ad_doc.get("text"):
            await query.answer("Set ad message first!", show_alert=True)
            return
        
        if user_id in campaign_tasks and not campaign_tasks[user_id].done():
            await query.answer("Campaign already running!", show_alert=True)
            return
        
        await db.campaigns.update_one(
            {"user_id": user_id},
            {"$set": {"active": True, "started_at": datetime.now(timezone.utc)}},
            upsert=True
        )
        task = asyncio.create_task(broadcast_loop(user_id, context))
        campaign_tasks[user_id] = task
        await query.answer("▶️ Campaign started!", show_alert=True)
        markup, text = kb_dashboard(user_id)
        await safe_edit_or_send(query, text, markup)
        return
    
    elif action == "stop":
        if user_id not in campaign_tasks or campaign_tasks[user_id].done():
            await query.answer("No running campaign!", show_alert=True)
            return
        
        await db.campaigns.update_one(
            {"user_id": user_id},
            {"$set": {"active": False}}
        )
        campaign_tasks[user_id].cancel()
        del campaign_tasks[user_id]
        await query.answer("⏸️ Campaign stopped!", show_alert=True)
        markup, text = kb_dashboard(user_id)
        await safe_edit_or_send(query, text, markup)

async def broadcast_loop(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    ad_doc = await db.ads.find_one({"user_id": user_id})
    ad_text = ad_doc.get("text")
    delay_doc = await db.settings.find_one({"user_id": user_id})
    delay = delay_doc.get("delay", 300) if delay_doc else 300
    
    accounts = await db.accounts.find({"user_id": user_id, "active": True}).to_list(None)
    
    cycle = 0
    sent_total = 0
    failed_total = 0
    
    while True:
        cycle += 1
        sent_cycle = 0
        failed_cycle = 0
        
        for acc in accounts:
            try:
                client = TelegramClient(StringSession(acc["session"]), API_ID, API_HASH)
                await client.connect()
                await client.sign_in(phone=acc["phone"])
                
                async for dialog in client.iter_dialogs():
                    if dialog.is_group or dialog.is_channel:
                        try:
                            await client.send_message(dialog, ad_text)
                            sent_cycle += 1
                        except Exception as e:
                            failed_cycle += 1
                            logger.error(f"Send failed to {dialog.title}: {e}")
                
                await client.disconnect()
                await db.accounts.update_one({"_id": acc["_id"]}, {"$set": {"last_used": datetime.now(timezone.utc)}})
                
            except Exception as e:
                failed_cycle += 1
                logger.error(f"Account {acc['phone']} error: {e}")
        
        sent_total += sent_cycle
        failed_total += failed_cycle
        
        await db.stats.update_one(
            {"user_id": user_id},
            {"$inc": {"cycles": 1, "sent": sent_cycle, "failed": failed_cycle}},
            upsert=True
        )
        
        if not (await db.campaigns.find_one({"user_id": user_id})).get("active", False):
            break
        
        await asyncio.sleep(delay)
    
    # Update campaign to inactive
    await db.campaigns.update_one({"user_id": user_id}, {"$set": {"active": False}})

async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    action = parts[1]
    user_id = query.from_user.id

    if action == "main":
        stats_doc = await db.stats.find_one({"user_id": user_id}) or {}
        cycles = stats_doc.get("cycles", 0)
        sent = stats_doc.get("sent", 0)
        failed = stats_doc.get("failed", 0)
        accounts_count = await db.accounts.count_documents({"user_id": user_id, "active": True})
        delay_doc = await db.settings.find_one({"user_id": user_id})
        avg_delay = delay_doc.get("delay", 300) if delay_doc else 300
        success_rate = (sent / (sent + failed) * 100) if (sent + failed) > 0 else 0
        bar = "▓" * int(success_rate / 10) + "░" * (10 - int(success_rate / 10))
        
        text = (f"╰_╯@Tecxo ANALYTICS\n\n"
                f"Broadcast Cycles Completed: {cycles}\n"
                f"Messages Sent: {sent}\n"
                f"Failed Sends: {failed}\n"
                f"Logger Failures: 0\n"
                f"Active Accounts: {accounts_count}\n"
                f"Avg Delay: {avg_delay}s\n\n"
                f"Success Rate: {bar} {success_rate:.0f}%")
        
        await safe_edit_or_send(query, text, InlineKeyboardMarkup([
            [InlineKeyboardButton("Detailed Report", callback_data="stat|detail")],
            [InlineKeyboardButton("Back", callback_data="nav|dashboard")]
        ]))
        return
    
    elif action == "detail":
        stats_doc = await db.stats.find_one({"user_id": user_id}) or {}
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%d/%m/%y")
        
        text = (f"╰_╯ DETAILED ANALYTICS REPORT:\n\n"
                f"Date: {date_str}\n"
                f"User ID: {user_id}\n\n"
                f"Broadcast Stats:\n"
                f"- Total Sent: {stats_doc.get('sent', 0)}\n"
                f"- Total Failed: {stats_doc.get('failed', 0)}\n"
                f"- Total Broadcasts: {stats_doc.get('cycles', 0)}\n\n"
                f"Logger Stats:\n"
                f"- Logger Failures: 0\n"
                f"- Last Failure: None\n\n"
                f"Account Stats:\n"
                f"- Total Accounts: {await db.accounts.count_documents({'user_id': user_id})}\n"
                f"- Active Accounts: {await db.accounts.count_documents({'user_id': user_id, 'active': True})} 🟢\n"
                f"- Inactive Accounts: {await db.accounts.count_documents({'user_id': user_id, 'active': False})} 🔴\n\n"
                f"Current Delay: { (await db.settings.find_one({'user_id': user_id}) or {}).get('delay', 300) }s")
        
        await safe_edit_or_send(query, text, kb_detailed_report())

async def handle_features(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    action = parts[1]
    user_id = query.from_user.id

    if action == "auto":
        text = ("╰_╯AUTO REPLY FEATURE\n\n"
                "This feature is coming soon!\n"
                "Stay tuned for automated reply capabilities to enhance your campaigns. This in feature")
        await safe_edit_or_send(query, text, kb_auto_reply())

# --- Main ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(handle_navigation, pattern="^nav\\|"))
    app.add_handler(CallbackQueryHandler(handle_account_ops, pattern="^acc\\|"))
    app.add_handler(CallbackQueryHandler(handle_ad_ops, pattern="^ad\\|"))
    app.add_handler(CallbackQueryHandler(handle_delay_ops, pattern="^delay\\|"))
    app.add_handler(CallbackQueryHandler(handle_campaign_ops, pattern="^camp\\|"))
    app.add_handler(CallbackQueryHandler(handle_stats, pattern="^stat\\|"))
    app.add_handler(CallbackQueryHandler(handle_features, pattern="^feature\\|"))
    app.add_handler(CallbackQueryHandler(handle_otp, pattern="^otp\\|"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, input_handler))

    app.run_polling()

if __name__ == "__main__":
    main()