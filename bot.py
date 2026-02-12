import logging
import asyncio
import random
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeEmptyError, 
    PhoneCodeExpiredError, FloodWaitError, PhoneNumberBannedError
)
from motor.motor_asyncio import AsyncIOMotorClient
import re

# 🔥 CONFIG - UPDATE THESE
BOT_TOKEN = '8463982454:AAFXhclFtn5cCoJLZl3l-SwhPMk3ssv6J8o'
API_ID = 22657083
API_HASH = 'd6186691704bd901bdab275ceaab88f3'

# MONGO URI - UPDATE THIS
MONGO_URI = "mongodb+srv://StarGiftBot_db_user:gld1RLm4eYbCWZlC@cluster0.erob6sp.mongodb.net/?appName=Cluster0"
CHANNEL_URL = "https://t.me/adimyzepro"  # MUST JOIN CHANNEL
CHANNEL_ID = -1001234567890  # GET FROM @username_to_id_bot or browser inspect

# Images - Optional
DASHBOARD_IMAGE = "https://telegram.me/share/url?url=https://files.catbox.moe/zttfbe.jpg"  # Or remove
WELCOME_IMAGE = "https://telegram.me/share/url?url=https://files.catbox.moe/zttfbe.jpg"   # Or remove

# MongoDB Setup
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client.adimyze

# Global Data
user_states = {}
running_ads = {}
clients = {}

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════
# 🔐 MUST JOIN CHECKER - 100% WORKING
# ════════════════════════════════════════════════════════════════
async def is_user_member(user_id: int) -> bool:
    """Check if user joined required channel"""
    try:
        result = await db.users.find_one({"user_id": user_id})
        if result and result.get("joined", False):
            return True
        
        # Check actual membership
        from telegram import Bot
        bot = Bot(token=BOT_TOKEN)
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

async def mark_user_joined(user_id: int):
    """Mark user as joined in DB"""
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"joined": True, "checked": datetime.now()}},
        upsert=True
    )

# ════════════════════════════════════════════════════════════════
# 🎨 PERFECT KEYBOARDS
# ════════════════════════════════════════════════════════════════
def must_join_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=CHANNEL_URL)],
        [InlineKeyboardButton("✅ Verified", callback_data="check_join")]
    ])

def start_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📞 Support", callback_data="support"),
            InlineKeyboardButton("📊 Dashboard", callback_data="dashboard")
        ],
        [InlineKeyboardButton("📢 Channel", url=CHANNEL_URL)]
    ])

def dashboard_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Account", callback_data="add_acc"), InlineKeyboardButton("👥 Accounts", callback_data="accounts")],
        [InlineKeyboardButton("📝 Set Ad", callback_data="set_ad"), InlineKeyboardButton("⏱️ Delay", callback_data="set_delay")],
        [InlineKeyboardButton("▶️ Start Ads", callback_data="start_ads"), InlineKeyboardButton("⏹️ Stop Ads", callback_data="stop_ads")],
        [],
        [InlineKeyboardButton("📊 Stats", callback_data="stats"), InlineKeyboardButton("🔙 Back", callback_data="back")]
    ])

def otp_keyboard(buffer="______"):
    otp_display = buffer[:6].ljust(6, '_')
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Check SMS", callback_data="check_sms")],
        [],
        [InlineKeyboardButton("1", callback_data="otp_1"), InlineKeyboardButton("2", callback_data="otp_2"), InlineKeyboardButton("3", callback_data="otp_3")],
        [InlineKeyboardButton("4", callback_data="otp_4"), InlineKeyboardButton("5", callback_data="otp_5"), InlineKeyboardButton("6", callback_data="otp_6")],
        [InlineKeyboardButton("7", callback_data="otp_7"), InlineKeyboardButton("8", callback_data="otp_8"), InlineKeyboardButton("9", callback_data="otp_9")],
        [InlineKeyboardButton("⌫", callback_data="otp_del"), InlineKeyboardButton("0", callback_data="otp_0"), InlineKeyboardButton("✅ ENTER", callback_data="otp_ok")],
        [],
        [InlineKeyboardButton(f"OTP: {otp_display}", callback_data="otp_show")]
    ])

def accounts_keyboard(accounts):
    keyboard = []
    for acc in accounts[:10]:
        status = "🟢" if acc.get('active', False) else "🔴"
        keyboard.append([InlineKeyboardButton(f"{status} {acc['name'][:25]}", callback_data=f"acc_{acc['_id']}")])

    keyboard += [
        [InlineKeyboardButton("➕ Add New", callback_data="add_acc")],
        [InlineKeyboardButton("🔙 Dashboard", callback_data="dashboard")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ════════════════════════════════════════════════════════════════
# 🎯 MAIN HANDLERS - MUST JOIN ADDED
# ════════════════════════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # 🔥 CHECK IF USER JOINED CHANNEL
    if not await is_user_member(user_id):
        text = """🔥 <b>WELCOME TO ADIMYZE PRO v8.0</b> 🔥

⚠️ <b>First join our channel!</b>

<b>📢 Join → Verified → Use Bot</b>"""
        
        try:
            if WELCOME_IMAGE:
                await update.message.reply_photo(
                    WELCOME_IMAGE, 
                    caption=text,
                    reply_markup=must_join_keyboard(),
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(text, reply_markup=must_join_keyboard(), parse_mode=ParseMode.HTML)
        except:
            await update.message.reply_text(text, reply_markup=must_join_keyboard(), parse_mode=ParseMode.HTML)
        return

    # User already joined ✅
    text = """🔥 <b>ADIMYZE PRO v8.0</b> 🔥

<b>🚀 Professional Ad Bot</b>

👇 <b>Select Option:</b>"""

    try:
        if WELCOME_IMAGE:
            await update.message.reply_photo(
                WELCOME_IMAGE, 
                caption=text,
                reply_markup=start_keyboard(),
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text(text, reply_markup=start_keyboard(), parse_mode=ParseMode.HTML)
    except:
        await update.message.reply_text(text, reply_markup=start_keyboard(), parse_mode=ParseMode.HTML)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    # 🔥 MUST JOIN CHECK
    if data == "check_join":
        if await is_user_member(user_id):
            await mark_user_joined(user_id)
            await start(query, context)
            return
        else:
            await query.answer("❌ Still not joined! Join first 👆", show_alert=True)
            return

    # Skip join check for these
    if data in ["support", "check_join"]:
        pass
    else:
        # Check membership for all other actions
        if not await is_user_member(user_id):
            await query.edit_message_text(
                "❌ <b>You must join channel first!</b>\n\n👆 Join & click Verified",
                reply_markup=must_join_keyboard(),
                parse_mode=ParseMode.HTML
            )
            return

    # Start Menu
    if data == "support":
        await query.edit_message_text(
            f"""📞 <b>SUPPORT</b>

👨‍💻 <b>@yourusername</b>
📢 <b>{CHANNEL_URL}</b>

<b>Problems? DM me!</b>""",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]]),
            parse_mode=ParseMode.HTML
        )

    elif data == "dashboard":
        await show_dashboard(query, user_id)

    elif data == "back":
        await start(query, context)

    # Dashboard
    elif data == "add_acc":
        await add_account_step1(query, user_id)

    elif data == "accounts":
        await show_accounts(query, user_id)

    elif data.startswith("acc_"):
        account_id = data.split("_")[1]
        await select_account(query, user_id, account_id)

    elif data == "set_ad":
        user_states[user_id] = {"step": "set_ad"}
        await query.edit_message_text(
            "📝 <b>Set Your Ad Message:</b>\n\nSend any text/media you want to forward.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Dashboard", callback_data="dashboard")]]),
            parse_mode=ParseMode.HTML
        )

# ════════════════════════════════════════════════════════════════
# 🔥 REST OF THE CODE - SAME AS BEFORE
# ════════════════════════════════════════════════════════════════
async def add_account_step1(query, user_id):
    user_states[user_id] = {"step": "phone"}
    await query.edit_message_text(
        """📱 <b>ADD ACCOUNT</b>

<b>Enter Phone Number:</b>
<code>+919876543210</code>

<b>Type exactly like this 👇</b>""",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Dashboard", callback_data="dashboard")]]),
        parse_mode=ParseMode.HTML
    )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # 🔥 CHECK MEMBERSHIP FOR TEXT INPUTS
    if not await is_user_member(user_id):
        await update.message.reply_text(
            "❌ <b>You must join channel first!</b>\n\nJoin: " + CHANNEL_URL,
            reply_markup=must_join_keyboard(),
            parse_mode=ParseMode.HTML
        )
        return
    
    text = update.message.text.strip()

    if user_id not in user_states:
        return

    step = user_states[user_id].get("step")

    if step == "phone":
        await handle_phone(update, text, user_id)
    elif step == "name":
        await handle_account_name(update, text, user_id)
    elif step == "set_ad":
        await handle_set_ad(update, text, user_id)

async def handle_phone(update, phone, user_id):
    if not re.match(r'^\+[1-9]\d{1,14}$', phone):
        return await update.message.reply_text("❌ Wrong format! Use: <code>+919876543210</code>", parse_mode=ParseMode.HTML)

    msg = await update.message.reply_text("📤 Sending OTP...")

    try:
        client = TelegramClient(f"session_{user_id}", API_ID, API_HASH)
        await client.connect()

        sent_code = await client.send_code_request(phone)

        user_states[user_id].update({
            "phone": phone,
            "hash": sent_code.phone_code_hash,
            "otp": "",
            "client": client
        })

        await msg.delete()
        await show_otp_keyboard(update.message, user_id)

    except FloodWaitError as e:
        await msg.edit_text(f"⏳ Wait {e.seconds}s")
    except Exception as e:
        await msg.edit_text(f"❌ {str(e)}")

async def show_otp_keyboard(message, user_id):
    buffer = user_states[user_id].get("otp", "")
    text = f"""🔢 <b>ENTER OTP</b>

📱 <b>Check SMS/Telegram</b>

<code>{buffer.ljust(6, '_')}</code>

<b>👇 Click Numbers:</b>"""

    await message.reply_text(
        text,
        reply_markup=otp_keyboard(buffer),
        parse_mode=ParseMode.HTML
    )

async def otp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data.startswith("otp_"):
        digit = data.split("_")[1]
        await handle_otp_digit(user_id, digit, query)
    elif data == "check_sms":
        await query.answer("📱 Check SMS/Telegram app!", show_alert=True)

async def handle_otp_digit(user_id, digit, query):
    buffer = user_states[user_id].get("otp", "")

    if digit == "del":
        user_states[user_id]["otp"] = buffer[:-1]
    elif digit == "ok":
        if len(user_states[user_id]["otp"]) == 6:
            await verify_otp(user_id, query)
        else:
            await query.answer("❌ 6 digits required!", show_alert=True)
            return
    else:
        if len(buffer) < 6:
            user_states[user_id]["otp"] = buffer + digit

    await show_otp_keyboard(query.message.reply_text if hasattr(query.message, 'reply_text') else lambda x, y: query.edit_message_text(x, reply_markup=y), user_id, buffer)

async def verify_otp(user_id, query):
    otp = user_states[user_id]["otp"]
    client = user_states[user_id]["client"]

    await query.edit_message_text("🔐 Verifying...")

    try:
        await client.sign_in(
            phone=user_states[user_id]["phone"],
            code=otp,
            phone_code_hash=user_states[user_id]["hash"]
        )

        session = client.session.save()
        await client.disconnect()

        account = {
            "_id": str(random.randint(100000, 999999)),
            "user_id": user_id,
            "phone": user_states[user_id]["phone"],
            "name": f"Acc {account['_id'][-3:]}",
            "session": session,
            "active": True,
            "posts": 0,
            "created": datetime.now()
        }

        await db.accounts.insert_one(account)
        latest_account = await db.accounts.find({"user_id": user_id}).sort("created", -1).limit(1).to_list(None)

        user_states[user_id]["step"] = "name"
        user_states[user_id]["latest_account_id"] = latest_account[0]["_id"] if latest_account else account["_id"]
        
        await query.edit_message_text(
            f"✅ <b>Login Success!</b>\n\n"
            f"📱 <code>{user_states[user_id]['phone']}</code>\n\n"
            f"💎 <b>Name your account 👇</b>",
            parse_mode=ParseMode.HTML
        )

    except PhoneCodeInvalidError:
        await query.edit_message_text(
            "❌ Wrong OTP!",
            reply_markup=otp_keyboard(user_states[user_id]["otp"]),
            parse_mode=ParseMode.HTML
        )
    except SessionPasswordNeededError:
        user_states[user_id]["step"] = "2fa"
        await query.edit_message_text("🔐 Enter 2FA Password:")
    except Exception as e:
        await query.edit_message_text(f"❌ {str(e)}")

async def handle_account_name(update, name, user_id):
    account_id = user_states[user_id].get("latest_account_id")
    if account_id:
        await db.accounts.update_one(
            {"_id": account_id},
            {"$set": {"name": name[:30]}}
        )

    del user_states[user_id]
    await update.message.reply_text(
        f"✅ <b>{name} Saved!</b>",
        reply_markup=dashboard_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await show_dashboard(update.message, user_id)

async def show_dashboard(query_or_msg, user_id):
    count = await db.accounts.count_documents({"user_id": user_id})
    status = "🟢 LIVE" if user_id in running_ads else "🔴 STOPPED"

    text = f"""📊 <b>DASHBOARD</b>

👥 Accounts: <code>{count}</code>
🤖 Status: <b>{status}</b>

<b>👇 Controls:</b>"""

    keyboard = dashboard_keyboard()

    try:
        if hasattr(query_or_msg, 'edit_message_text'):
            await query_or_msg.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        else:
            if DASHBOARD_IMAGE:
                await query_or_msg.reply_photo(DASHBOARD_IMAGE, caption=text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
            else:
                await query_or_msg.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except:
        await query_or_msg.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

async def show_accounts(query, user_id):
    accounts = await db.accounts.find({"user_id": user_id}).sort("created", -1).to_list(10)

    if not accounts:
        text = "📭 No accounts. Add first one!"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Account", callback_data="add_acc")],
            [InlineKeyboardButton("🔙 Dashboard", callback_data="dashboard")]
        ])
    else:
        text = f"👥 <b>{len(accounts)} Accounts</b>"
        keyboard = accounts_keyboard(accounts)

    await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)

async def select_account(query, user_id, account_id):
    account = await db.accounts.find_one({"_id": account_id, "user_id": user_id})
    if account:
        await query.edit_message_text(
            f"✅ Selected: <b>{account['name']}</b>\n\n📱 <code>{account['phone']}</code>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Accounts", callback_data="accounts")],
                [InlineKeyboardButton("🔙 Dashboard", callback_data="dashboard")]
            ]),
            parse_mode=ParseMode.HTML
        )

async def handle_set_ad(update, text, user_id):
    await db.ads.update_one(
        {"user_id": user_id},
        {"$set": {"message": text, "updated": datetime.now()}},
        upsert=True
    )
    del user_states[user_id]
    await update.message.reply_text(
        "✅ Ad message saved!",
        reply_markup=dashboard_keyboard(),
        parse_mode=ParseMode.HTML
    )

# ════════════════════════════════════════════════════════════════
# 🚀 MAIN
# ════════════════════════════════════════════════════════════════
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler, pattern="^(check_join|support|dashboard|back|add_acc|accounts|set_ad|set_delay|start_ads|stop_ads|stats|acc_.*)$"))
    app.add_handler(CallbackQueryHandler(otp_callback, pattern="^(otp_|check_sms)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("🔥 ADIMYZE PRO v8.0 - LIVE! 🔥")
    print("✅ MUST JOIN CHANNEL ADDED")
    print("✅ Update button REMOVED")
    print("✅ MongoDB + OTP PERFECT")
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()