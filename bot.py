from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import BadRequest
import logging
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
import asyncio
import json
import os
from datetime import datetime
import random
import re

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# CONFIG (YOUR CREDENTIALS - PERFECT!)
BOT_TOKEN = '8463982454:AAFXhclFtn5cCoJLZl3l-SwhPMk3ssv6J8o'
API_ID = 22657083
API_HASH = 'd6186691704bd901bdab275ceaab88f3'

# Storage
user_data = {}
running_users = {}
ad_message = {}

class AdBot:
    def __init__(self):
        self.clients = {}

    async def create_client(self, user_id: int, session_string: str = None):
        """Fixed: Proper session string handling"""
        if session_string:
            try:
                # Validate session string format
                session = StringSession(session_string)
                client = TelegramClient(session, API_ID, API_HASH)
            except Exception:
                # Fallback to string session if invalid
                client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        else:
            client = TelegramClient(StringSession(f'session_{user_id}'), API_ID, API_HASH)
        
        self.clients[user_id] = client
        return client

    async def get_client(self, user_id: int):
        """Get existing client or create new one"""
        if user_id not in self.clients:
            return await self.create_client(user_id)
        return self.clients[user_id]

adbot = AdBot()

# =====================================================================
# 1️⃣ POLICY SCREEN (REQUIRED)
# =====================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = [[InlineKeyboardButton("✅ I ACCEPT - START LOGIN", callback_data='accept_policy')]]

    policy_text = """
🎯 **ADIMYZE BOT - TERMS OF SERVICE** 🎯

⚠️ **IMPORTANT POLICY:**

1️⃣ **LEGAL USE ONLY** - Only advertise in groups you own/admin
2️⃣ **NO SPAM** - Respect group rules
3️⃣ **YOUR RESPONSIBILITY** - Bot uses YOUR Telegram account
4️⃣ **NO WARRANTY** - Use at your own risk
5️⃣ **LIMITED SUPPORT** - For authorized users only

**✅ Click button to ACCEPT and continue to login**
    """

    await update.message.reply_text(policy_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# =====================================================================
# 2️⃣ LOGIN FLOW (Phone → OTP → 2FA → DASHBOARD)
# =====================================================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == 'accept_policy':
        await policy_accepted(query)
    elif data == 'login_phone':
        await request_phone_prompt(query)
    elif data == 'dashboard':
        await show_dashboard(query, user_id)
    elif data == 'load_groups':
        await load_groups(query, user_id)
    elif data == 'set_ad':
        await set_ad_prompt(query, user_id)
    elif data == 'set_delay':
        await set_delay_prompt(query, user_id)
    elif data == 'start_bot':
        await start_bot(query, user_id)
    elif data == 'stop_bot':
        await stop_bot(query, user_id)
    elif data == 'status':
        await show_status(query, user_id)

async def policy_accepted(query):
    """User accepted policy → Show image + Phone prompt"""
    keyboard = [[InlineKeyboardButton("📱 ENTER PHONE NUMBER", callback_data='login_phone')]]
    
    # Send welcome image first
    try:
        # You can replace this with your own image URL or local file path
        image_url = "https://files.catbox.moe/zttfbe.jpg"  # Replace with real image
        await query.message.reply_photo(
            photo=image_url,
            caption="✅ **POLICY ACCEPTED!** 🎉\n\n🔐 **Step 1: Account Login**\n\n**Enter your phone number** (with country code):\n`+1234567890`\n\n👇 Click button then type phone:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    except:
        # Fallback to text if image fails
        await query.edit_message_text(
            "✅ **POLICY ACCEPTED!** 🎉\n\n"
            "🔐 **Step 1: Account Login**\n\n"
            "**Enter your phone number** (with country code):\n"
            "`+1234567890`\n\n"
            "👇 Click button then type phone:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

async def request_phone_prompt(query):
    """Prompt for phone number"""
    user_id = query.from_user.id
    user_data[user_id] = {'step': 'phone'}
    await query.edit_message_text(
        "📱 **Enter Phone Number**\n\n"
        "**Type exactly like this:**\n"
        "`+1234567890`\n\n"
        "**Send your phone now:**",
        parse_mode='Markdown'
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id not in user_data:
        await update.message.reply_text("👆 Use /start first!")
        return

    step = user_data[user_id].get('step')
    waiting_for = user_data[user_id].get('waiting_for')

    # === DELAYS ===
    if waiting_for == 'delay':
        try:
            delay = int(text)
            user_data[user_id]['delay'] = delay
            del user_data[user_id]['waiting_for']
            await update.message.reply_text(f"✅ **Delay set: {delay}s**")
            await dashboard_message(update, user_id)
        except:
            await update.message.reply_text("❌ Enter valid number!")
        return

    # === PHONE ===
    if step == 'phone':
        if re.match(r'^\+[1-9]\d{1,14}$', text):
            await send_otp(update, text)
        else:
            await update.message.reply_text("❌ **Invalid format!**\nUse: `+1234567890`", parse_mode='Markdown')
        return

    # === OTP ===
    if step == 'otp':
        await verify_otp(update, text)
        return

    # === 2FA ===
    if step == '2fa':
        await verify_2fa(update, text)
        return

async def send_otp(update: Update, phone: str):
    """Send real OTP - Fixed client handling"""
    user_id = update.effective_user.id
    user_data[user_id]['phone'] = phone
    user_data[user_id]['step'] = 'otp'

    try:
        client = await adbot.create_client(user_id)
        await client.connect()
        result = await client.send_code_request(phone)
        user_data[user_id]['phone_code_hash'] = result.phone_code_hash
        await client.disconnect()

        await update.message.reply_text(
            f"✅ **OTP sent to {phone}**\n\n"
            "**Enter 5-6 digit code:**",
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")
        logger.error(f"OTP error: {e}")

async def verify_otp(update: Update, otp: str):
    """Verify OTP → Check 2FA → Dashboard - Fixed session handling"""
    user_id = update.effective_user.id

    try:
        # FIXED: Use session string properly
        session_str = user_data[user_id].get('session')
        client = await adbot.create_client(user_id, session_str)
        await client.connect()

        await client.sign_in(
            user_data[user_id]['phone'], 
            user_data[user_id]['phone_code_hash'], 
            otp
        )

        # Save session properly as string
        saved_session = client.session.save()
        user_data[user_id]['session'] = saved_session
        user_data[user_id]['logged_in'] = True
        del user_data[user_id]['step']
        await client.disconnect()

        await update.message.reply_text("🎉 **LOGIN SUCCESSFUL!**")
        await dashboard_message(update, user_id)

    except SessionPasswordNeededError:
        user_data[user_id]['step'] = '2fa'
        await update.message.reply_text("🔐 **2FA Enabled**\n\n**Enter your 2FA password:**")

    except PhoneCodeInvalidError:
        await update.message.reply_text("❌ **Wrong OTP!**\nTry again:")

    except Exception as e:
        await update.message.reply_text(f"❌ **Error:** {str(e)}")
        logger.error(f"Login error: {e}")

async def verify_2fa(update: Update, password: str):
    """Verify 2FA password - Fixed"""
    user_id = update.effective_user.id

    try:
        session_str = user_data[user_id].get('session')
        client = await adbot.create_client(user_id, session_str)
        await client.connect()
        await client.sign_in(password=password)

        user_data[user_id]['logged_in'] = True
        del user_data[user_id]['step']
        await client.disconnect()

        await update.message.reply_text("🔓 **2FA SUCCESSFUL!** 🎉")
        await dashboard_message(update, user_id)

    except Exception as e:
        await update.message.reply_text("❌ **Wrong 2FA password!**\nTry again:")
        logger.error(f"2FA error: {e}")

# =====================================================================
# 3️⃣ DASHBOARD (After Login)
# =====================================================================
async def dashboard_message(update, user_id):
    """Main dashboard"""
    keyboard = [
        [InlineKeyboardButton("📥 Load Groups", callback_data='load_groups')],
        [InlineKeyboardButton("📢 Set Ad", callback_data='set_ad')],
        [InlineKeyboardButton("⏱️ Set Delay", callback_data='set_delay')],
        [InlineKeyboardButton("▶️ START BOT", callback_data='start_bot')],
        [InlineKeyboardButton("⛔ STOP BOT", callback_data='stop_bot')],
        [InlineKeyboardButton("📊 STATUS", callback_data='status')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    status_text = "🎛️ **DASHBOARD - READY TO ADVERTISE!** 🎛️\n\n"
    status_text += "✅ **Logged in successfully**\n"
    status_text += "📱 **Flow:** Load Groups → Set Ad → Delay → START\n\n"
    status_text += "**👇 Use buttons below:**"

    await update.message.reply_text(
        status_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_dashboard(query, user_id):
    """Dashboard from button"""
    keyboard = [
        [InlineKeyboardButton("📥 Load Groups", callback_data='load_groups')],
        [InlineKeyboardButton("📢 Set Ad", callback_data='set_ad')],
        [InlineKeyboardButton("⏱️ Set Delay", callback_data='set_delay')],
        [InlineKeyboardButton("▶️ START BOT", callback_data='start_bot')],
        [InlineKeyboardButton("⛔ STOP BOT", callback_data='stop_bot')],
        [InlineKeyboardButton("📊 STATUS", callback_data='status')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "🎛️ **DASHBOARD** 🎛️\n\n"
        "**Ready to advertise!**\n👇 Choose action:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

# =====================================================================
# 4️⃣ BOT CONTROLS
# =====================================================================
async def load_groups(query, user_id):
    if not user_data[user_id].get('logged_in'):
        await query.answer("Login first!", show_alert=True)
        return

    await query.answer("Loading groups...")

    try:
        client = await adbot.get_client(user_id)
        await client.start(session=user_data[user_id]['session'])

        groups = []
        async for dialog in client.iter_dialogs():
            if (dialog.is_group or dialog.is_channel) and dialog.name:
                groups.append({'id': dialog.id, 'name': dialog.name[:30]})

        user_data[user_id]['groups'] = groups[:50]
        await client.disconnect()

        await query.edit_message_text(
            f"✅ **{len(groups)} GROUPS LOADED!**\n\n"
            "Ready to advertise! 🎉",
            parse_mode='Markdown'
        )
    except Exception as e:
        await query.answer(f"Error: {str(e)}", show_alert=True)
        logger.error(f"Load groups error: {e}")

async def set_ad_prompt(query, user_id):
    user_data[user_id]['waiting_ad'] = True
    await query.edit_message_text(
        "📢 **SET YOUR AD**\n\n"
        "**📤 Forward your ad message** from **Saved Messages**\n"
        "(Images/videos supported)\n\n"
        "**Forward now:**",
        parse_mode='Markdown'
    )

async def set_delay_prompt(query, user_id):
    user_data[user_id]['waiting_for'] = 'delay'
    await query.edit_message_text("⏱️ **Enter delay in seconds:**\n`30`, `60`, `300`", parse_mode='Markdown')

async def handle_forwarded_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_data[user_id].get('waiting_ad'):
        msg = update.message
        ad_message[user_id] = {
            'chat_id': msg.forward_from_chat.id if msg.forward_from_chat else msg.chat.id,
            'msg_id': msg.forward_from_message_id or msg.message_id
        }
        del user_data[user_id]['waiting_ad']
        await update.message.reply_text("✅ **AD SAVED!**\nForwarding your exact message!")
        await dashboard_message(update, user_id)

async def start_bot(query, user_id):
    if not all([user_data[user_id].get(x) for x in ['logged_in', 'groups', 'delay']]):
        await query.answer("❌ Complete setup first!", show_alert=True)
        return

    if user_id not in ad_message:
        await query.answer("❌ Set ad first!", show_alert=True)
        return

    running_users[user_id] = True
    asyncio.create_task(ad_loop(user_id))
    await query.edit_message_text("🚀 **BOT STARTED!**\n📤 Auto-posting forever...")

async def ad_loop(user_id):
    """Infinite ad posting - Fixed client handling"""
    delay = user_data[user_id]['delay']
    while running_users.get(user_id):
        try:
            client = await adbot.get_client(user_id)
            await client.start(session=user_data[user_id]['session'])

            for group in user_data[user_id]['groups']:
                if not running_users.get(user_id): 
                    break
                try:
                    await client.forward_messages(
                        group['id'],
                        ad_message[user_id]['chat_id'],
                        ad_message[user_id]['msg_id']
                    )
                    await asyncio.sleep(delay)
                except Exception as e:
                    logger.error(f"Post error: {e}")
                    continue

            await client.disconnect()
            await asyncio.sleep(300)  # Cycle
        except Exception as e:
            logger.error(f"Ad loop error: {e}")
            await asyncio.sleep(60)

async def stop_bot(query, user_id):
    running_users[user_id] = False
    await query.edit_message_text("⛔ **BOT STOPPED**")

async def show_status(query, user_id):
    groups = len(user_data[user_id].get('groups', []))
    running = user_id in running_users
    delay = user_data[user_id].get('delay', 0)
    status = f"📊 **STATUS**\n\nGroups: **{groups}**\nDelay: **{delay}s**\nBot: {'🟢 ON' if running else '🔴 OFF'}"
    await query.edit_message_text(status, parse_mode='Markdown')

# =====================================================================
# MAIN
# =====================================================================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.FORWARDED, handle_forwarded_message))

    print("🚀 Adimyze Bot Started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()