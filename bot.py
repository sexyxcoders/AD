import asyncio
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Dict, Optional, List
from dataclasses import dataclass
import json
from concurrent.futures import ThreadPoolExecutor

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
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty, Dialog
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    FloodWaitError,
    PeerFloodError,
    UserPrivacyRestrictedError,
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
    delay_seconds: int = 300
    campaign_active: bool = False
    broadcast_job: Optional[asyncio.Task] = None

user_states: Dict[int, UserState] = {}
campaigns: Dict[int, Dict] = {}  # user_id -> campaign_data

# ────────────────────────────────────────────────
# SAFE MESSAGE EDITING
# ────────────────────────────────────────────────

async def safe_edit_or_send(query, text: str, reply_markup=None):
    try:
        await query.edit_message_caption(caption=text, reply_markup=reply_markup)
        return
    except BadRequest:
        pass
    
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup)
        return
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

# ────────────────────────────────────────────────
# KEYBOARDS
# ────────────────────────────────────────────────

def kb_start():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("     🚀 Dashboard       ", callback_data="nav|dashboard")],
        [InlineKeyboardButton("📢 Updates", url="https://t.me/testttxs"),
         InlineKeyboardButton("💬 Support", url="https://t.me/nexaxoders")],
        [InlineKeyboardButton("     📖 How to Use      ", callback_data="nav|howto")],
        [InlineKeyboardButton("       👨‍💻 Powered By    ", url="https://t.me/nexaxoders")]
    ])

def kb_dashboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Accounts", callback_data="acc|add"),
         InlineKeyboardButton("📱 My Accounts", callback_data="acc|list|0")],
        [InlineKeyboardButton("✍️ Set Ad Message", callback_data="ad|set"),
         InlineKeyboardButton("⏱️ Set Interval", callback_data="delay|nav")],
        [InlineKeyboardButton("▶️  Start Ads", callback_data="camp|start"),
         InlineKeyboardButton("⏹️  Stop Ads", callback_data="camp|stop")],
        [InlineKeyboardButton("🗑️ Delete Accounts", callback_data="acc|del"),
         InlineKeyboardButton("📊 Analytics", callback_data="stat|main")],
        [InlineKeyboardButton("🤖 Auto Reply", callback_data="feature|auto"),
         InlineKeyboardButton("🔙 Back", callback_data="nav|start")]
    ])

def kb_otp(state: UserState):
    display = (state.otp_buffer + "○" * (5 - len(state.otp_buffer)))[:5]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔑 OTP: {display}", callback_data="ignore")],
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
        [InlineKeyboardButton("👁️ Show Code", url="tg://openmessage?user_id=777000")]
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
        [InlineKeyboardButton("🔙 Back", callback_data="nav|dashboard")]
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
        nav.append(InlineKeyboardButton("➡️ Next", callback_data=f"acc|list|{page+1}"))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="nav|dashboard")])
    return InlineKeyboardMarkup(buttons)

def kb_account_detail(acc_id: str, phone: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ Delete Account", callback_data=f"acc|delete|{acc_id}")],
        [InlineKeyboardButton("📋 Back to List", callback_data="acc|list|0")],
        [InlineKeyboardButton("🏠 Dashboard", callback_data="nav|dashboard")]
    ])

def kb_confirm_delete(acc_id: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, Delete", callback_data=f"acc|confirm_del|{acc_id}"),
         InlineKeyboardButton("❌ No", callback_data="nav|dashboard")]
    ])

def kb_stats(campaign: dict):
    status = "🟢 LIVE" if campaign.get("active", False) else "🔴 STOPPED"
    total_sent = campaign.get("total_sent", 0)
    success_rate = campaign.get("success_rate", 0)
    
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📊 Status: {status}", callback_data="ignore")],
        [InlineKeyboardButton(f"📤 Total Sent: {total_sent}", callback_data="ignore")],
        [InlineKeyboardButton(f"✅ Success: {success_rate}%", callback_data="ignore")],
        [InlineKeyboardButton("🔙 Dashboard", callback_data="nav|dashboard")]
    ])

# ────────────────────────────────────────────────
# BROADCAST FUNCTIONS
# ────────────────────────────────────────────────

async def get_user_groups(client: TelegramClient) -> List[Dialog]:
    """Get all groups/supergroups/channels the account can post to"""
    try:
        dialogs = await client(GetDialogsRequest(
            offset_date=None,
            offset_id=0,
            offset_peer=InputPeerEmpty(),
            limit=200,
            hash=0
        ))
        groups = []
        for dialog in dialogs.chats:
            if hasattr(dialog, 'megagroup') and dialog.megagroup:
                groups.append(dialog)
            elif hasattr(dialog, 'broadcast') and dialog.broadcast:
                groups.append(dialog)
            elif dialog.__class__.__name__ == 'Channel' and not dialog.creator:
                groups.append(dialog)
        return groups
    except Exception as e:
        logger.error(f"Error getting groups: {e}")
        return []

async def broadcast_from_account(client: TelegramClient, ad_text: str, account_id: str) -> dict:
    """Broadcast message from single account to all its groups"""
    try:
        groups = await get_user_groups(client)
        results = {"success": 0, "failed": 0, "total": len(groups), "groups": []}
        
        for group in groups:
            try:
                await client.send_message(group, ad_text)
                results["success"] += 1
                results["groups"].append(f"✅ {group.title}")
                logger.info(f"Sent to {group.title} from {account_id}")
                await asyncio.sleep(2)  # Anti-flood delay
            except (PeerFloodError, FloodWaitError) as e:
                results["failed"] += 1
                results["groups"].append(f"❌ {group.title} (Flood)")
                logger.warning(f"Flood error in {group.title}: {e}")
                await asyncio.sleep(60)
            except UserPrivacyRestrictedError:
                results["failed"] += 1
                results["groups"].append(f"🔒 {group.title} (Restricted)")
            except Exception as e:
                results["failed"] += 1
                results["groups"].append(f"❌ {group.title} ({str(e)[:20]})")
        
        return results
    except Exception as e:
        logger.error(f"Account {account_id} broadcast failed: {e}")
        return {"success": 0, "failed": 1, "total": 0}

async def run_campaign_cycle(user_id: int):
    """Run one complete campaign cycle across all accounts"""
    try:
        accounts = await db.accounts.find({"user_id": user_id, "active": True}).to_list(None)
        ad_doc = await db.ads.find_one({"user_id": str(user_id)})
        if not ad_doc or not accounts:
            logger.warning(f"No ad or accounts for user {user_id}")
            return
        
        ad_text = ad_doc["text"]
        campaign = campaigns.get(user_id, {"total_sent": 0, "cycles": 0, "success_rate": 0})
        
        all_results = []
        total_success = 0
        total_groups = 0
        
        # Create clients for all accounts and broadcast simultaneously
        tasks = []
        for acc in accounts:
            client = TelegramClient(StringSession(acc["session"]), API_ID, API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                task = asyncio.create_task(broadcast_from_account(client, ad_text, str(acc["_id"])))
                tasks.append((task, client))
        
        # Wait for all broadcasts to complete
        for task, client in tasks:
            try:
                result = await task
                all_results.append(result)
                total_success += result["success"]
                total_groups += result["total"]
                await client.disconnect()
            except Exception as e:
                logger.error(f"Task failed: {e}")
                await client.disconnect()
        
        # Update stats
        campaign["total_sent"] += total_success
        campaign["cycles"] += 1
        campaign["success_rate"] = round((total_success / total_groups * 100) if total_groups else 0, 1)
        campaigns[user_id] = campaign
        
        await db.campaigns.update_one(
            {"user_id": user_id},
            {"$set": {
                "stats": campaign,
                "last_cycle": datetime.now(timezone.utc)
            }},
            upsert=True
        )
        
        logger.info(f"Campaign cycle completed for {user_id}: {total_success} messages sent")
        
    except Exception as e:
        logger.error(f"Campaign cycle failed for {user_id}: {e}")

# ────────────────────────────────────────────────
# HANDLERS
# ────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "╭───────────── 🎉 WELCOME TO ADIMYZE PRO ╮\n\n"
        "🚀 Premium Ad Broadcasting Bot\n"
        "📱 Multi-Account Support\n"
        "⚡ Smart Anti-Flood System\n"
        "📊 Real-time Analytics\n\n"
        "💬 Support: @NexaCoders"
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
        return

    elif dest == "dashboard":
        text = "╭───────────── 🚀 DASHBOARD ╮\n\nManage your campaigns:"
        await safe_edit_or_send(query, text, kb_dashboard())

    elif dest == "howto":
        text = (
            "╭───────────── 📖 HOW TO USE ╮\n\n"
            "1️⃣ Add Account → Host your TG accounts\n"
            "2️⃣ Set Ad → Write your promo message\n"
            "3️⃣ Set Interval → Choose broadcast timing\n"
            "4️⃣ Start Ads → Bot sends to ALL GROUPS!\n\n"
            "⚠️ Each account sends to ALL its groups simultaneously"
        )
        await safe_edit_or_send(
            query, text,
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="nav|dashboard")]])
        )

async def handle_account_ops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    action = parts[1]
    user_id = query.from_user.id

    if action == "add":
        user_states[user_id] = UserState(step="phone")
        text = "📱 ADD NEW ACCOUNT\n\nEnter phone with country code:\n+1234567890"
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="nav|dashboard")]]))

    elif action == "list":
        page = int(parts[2])
        accounts = await db.accounts.find({"user_id": user_id}).to_list(None)
        text = f"📱 MY ACCOUNTS ({len(accounts)})\n\nChoose account:"
        await safe_edit_or_send(query, text, kb_accounts(accounts, page))

    elif action == "detail":
        acc_id = parts[2]
        acc = await db.accounts.find_one({"_id": acc_id, "user_id": user_id})
        if not acc:
            await query.answer("Account not found!", show_alert=True)
            return
        status = "🟢 Active" if acc.get("active") else "🔴 Inactive"
        text = f"📱 ACCOUNT INFO\n\nPhone: `{acc['phone']}`\nStatus: {status}"
        await safe_edit_or_send(query, text, kb_account_detail(acc_id, acc["phone"]))

    elif action == "delete":
        acc_id = parts[2]
        acc = await db.accounts.find_one({"_id": acc_id, "user_id": user_id})
        if not acc:
            await query.answer("Account not found!", show_alert=True)
            return
        text = f"⚠️ DELETE ACCOUNT\n\nRemove `{acc['phone']}`?"

elif action == "confirm_del":
        acc_id = parts[2]
        result = await db.accounts.delete_one({"_id": acc_id, "user_id": user_id})
        msg = "✅ Account deleted!" if result.deleted_count else "❌ Delete failed!"
        await query.answer(msg, show_alert=True)
        await safe_edit_or_send(query, "🏠 DASHBOARD", kb_dashboard())

    elif action == "del":
        count = await db.accounts.count_documents({"user_id": user_id})
        text = f"🗑️ DELETE ACCOUNTS\n\n{count} accounts found:"
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 View & Delete", callback_data="acc|list|0")],
            [InlineKeyboardButton("🔙 Back", callback_data="nav|dashboard")]
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
        del user_states[user_id]
        await safe_edit_or_send(query, "❌ Cancelled", kb_dashboard())
        return

    if action == "back":
        state.otp_buffer = state.otp_buffer[:-1]
    elif action.isdigit() and len(state.otp_buffer) < 5:
        state.otp_buffer += action

    if len(state.otp_buffer) == 5:
        await finalize_login(user_id, context)
        return

    masked = " ".join("•" if c.isdigit() else "_" for c in (state.otp_buffer + "     "))[:11:2]
    await safe_edit_or_send(query, f"🔑 OTP: {masked}", kb_otp(state))

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_states.get(user_id)
    if not state or state.step == "idle":
        return

    text = update.message.text.strip()

    if state.step == "phone":
        phone = "+" + re.sub(r"\D", "", text)
        if not (8 <= len(phone) <= 15):
            await update.message.reply_text("❌ Invalid phone format!")
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
                f"📱 OTP sent to {phone}\nUse buttons below:",
                reply_markup=kb_otp(state)
            )
        except FloodWaitError as e:
            await update.message.reply_text(f"⏳ Wait {e.seconds}s")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)[:100]}")
            await client.disconnect()

    elif state.step == "password":
        await finalize_login(user_id, context, password=text)
        del user_states[user_id]

    elif state.step == "set_ad":
        if len(text) > 4000:
            await update.message.reply_text("❌ Max 4000 chars!")
            return

        await db.ads.update_one(
            {"user_id": str(user_id)},
            {"$set": {"text": text, "updated_at": datetime.now(timezone.utc)}},
            upsert=True
        )
        del user_states[user_id]
        await update.message.reply_text("✅ Ad saved!", reply_markup=kb_dashboard())

async def finalize_login(user_id: int, context: ContextTypes.DEFAULT_TYPE, password: Optional[str] = None):
    state = user_states.get(user_id)
    if not state or not state.client:
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

        await state.client(UpdateProfileRequest(first_name=PROFILE_NAME, about=PROFILE_BIO))

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
        del user_states[user_id]

        await context.bot.send_message(
            user_id,
            f"✅ Account added!\n📱 {state.phone}\n👤 Profile: {PROFILE_NAME}",
            reply_markup=kb_dashboard()
        )

    except SessionPasswordNeededError:
        state.step = "password"
        await context.bot.send_message(user_id, "🔐 Send 2FA password:")
    except Exception as e:
        await context.bot.send_message(user_id, f"❌ Login failed: {str(e)[:100]}")

async def handle_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    parts = query.data.split("|")
    action = parts[1]

    state = user_states.get(user_id, UserState())
    user_states[user_id] = state

    if action == "start":
        accounts = await db.accounts.count_documents({"user_id": user_id, "active": True})
        ad_doc = await db.ads.find_one({"user_id": str(user_id)})
        
        if accounts == 0:
            await query.answer("Add accounts first!", show_alert=True)
            return
        if not ad_doc:
            await query.answer("Set ad message first!", show_alert=True)
            return

        if state.campaign_active:
            await query.answer("Campaign already running!", show_alert=True)
            return

        state.campaign_active = True
        state.broadcast_job = asyncio.create_task(campaign_loop(user_id, state.delay_seconds))
        
        campaigns[user_id] = {"active": True, "total_sent": 0, "cycles": 0}
        text = f"🚀 CAMPAIGN STARTED!\n📱 {accounts} accounts\n⏱️ Interval: {state.delay_seconds}s"
        await safe_edit_or_send(query, text, kb_dashboard())

    elif action == "stop":
        state.campaign_active = False
        if state.broadcast_job:
            state.broadcast_job.cancel()
        
        campaigns[user_id] = campaigns.get(user_id, {})
        campaigns[user_id]["active"] = False
        
        text = "⏹️ Campaign stopped!"
        await safe_edit_or_send(query, text, kb_dashboard())

async def campaign_loop(user_id: int, delay: int):
    """Main campaign loop"""
    while True:
        state = user_states.get(user_id)
        if not state or not state.campaign_active:
            break
            
        await run_campaign_cycle(user_id)
        await asyncio.sleep(delay)

async def handle_ads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    action = parts[1]
    user_id = query.from_user.id

    if action == "set":
        user_states[user_id] = UserState(step="set_ad")
        text = "✍️ SEND AD MESSAGE\n\nYour ad will be sent to ALL groups from ALL accounts!"
        await safe_edit_or_send(query, text, InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="nav|dashboard")]]))

async def handle_delay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    
    if parts[1] == "nav":
        state = user_states.get(query.from_user.id, UserState())
        await safe_edit_or_send(query, "⏱️ SET INTERVAL", kb_delay(state.delay_seconds))
    
    elif parts[1] == "setdelay":
        delay = int(parts[2])
        user_id = query.from_user.id
        state = user_states.get(user_id, UserState(delay_seconds=delay))
        state.delay_seconds = delay
        user_states[user_id] = state
        
        await query.answer(f"✅ Set to {delay//60} min", show_alert=True)
        await safe_edit_or_send(query, "🏠 DASHBOARD", kb_dashboard())

async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    campaign = campaigns.get(user_id, {"total_sent": 0, "cycles": 0, "success_rate": 0})
    text = (
        f"📊 ANALYTICS\n\n"
        f"📤 Total Messages: {campaign.get('total_sent', 0)}\n"
        f"🔄 Cycles: {campaign.get('cycles', 0)}\n"
        f"✅ Success Rate: {campaign.get('success_rate', 0)}%"
    )
    await safe_edit_or_send(query, text, kb_stats(campaign))

# ────────────────────────────────────────────────
# MAIN
# ────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(handle_navigation, pattern=r"^nav\|"))
    app.add_handler(CallbackQueryHandler(handle_account_ops, pattern=r"^acc\|"))
    app.add_handler(CallbackQueryHandler(handle_otp_input, pattern=r"^otp\|"))
    app.add_handler(CallbackQueryHandler(handle_campaign, pattern=r"^camp\|"))
    app.add_handler(CallbackQueryHandler(handle_ads, pattern=r"^ad\|"))
    app.add_handler(CallbackQueryHandler(handle_delay, pattern=r"^delay\|"))
    app.add_handler(CallbackQueryHandler(handle_stats, pattern=r"^stat\|"))
    app.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer(), pattern=r"^ignore$"))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))

    print("🚀 Adimyze Pro Bot Started - Broadcasting to ALL GROUPS!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()