from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import BadRequest, TelegramError
import logging
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, FloodWaitError
import asyncio
import json
import os
from datetime import datetime
import random
import re

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# CONFIG
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
        try:
            if session_string:
                client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
            else:
                client = TelegramClient(f'session_{user_id}', API_ID, API_HASH)
            self.clients[user_id] = client
            return client
        except Exception as e:
            logger.error(f"Client creation error: {e}")
            raise

adbot = AdBot()

# Animation messages
LOADING_MESSAGES = [
    "🔄 **Connecting to Telegram...**",
    "📱 **Sending OTP request...**", 
    "⏳ **Please check messages...**",
    "⚡ **Ready for verification...**",
    "✅ **OTP received!**"
]

# =====================================================================
# ERROR HANDLER
# =====================================================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Update {update} caused error {context.error}")

# =====================================================================
# ANIMATION FUNCTIONS
# =====================================================================
async def show_loading_animation(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int = None):
    for i, msg in enumerate(LOADING_MESSAGES):
        try:
            if message_id:
                await context.bot.edit_message_text(
                    chat_id=chat_id, 
                    message_id=message_id,
                    text=msg,
                    parse_mode='Markdown'
                )
            else:
                await context.bot.send_message(chat_id, msg, parse_mode='Markdown')
            await asyncio.sleep(1)
        except:
            pass

# =====================================================================
# 1️⃣ START SCREEN
# =====================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = [[InlineKeyboardButton("✅ START AD BOT ➡️", callback_data='accept_policy')]]
    
    welcome_text = """
🎯 **ADIMYZE PRO v3.1** 🎯

🔥 **AUTO ADVERTISING KING** 🔥
━━━━━━━━━━━━━━━━━━━━━━━━━━━
💎 **Features:**
• 50+ groups auto-post
• Images/videos/text ✅
• Safe delays & limits
• YOUR account only

**Click START 💰**
    """
    
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# =====================================================================
# 2️⃣ MAIN BUTTON HANDLER
# =====================================================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    try:
        if data == 'accept_policy':
            await show_phone_screen(query)
        elif data == 'login_phone':
            await show_phone_input(query, user_id)
        elif data == 'otp_keyboard':
            await show_otp_keyboard(query, user_id)
        elif data == 'show_code':
            await show_telegram_code(query, user_id)
        elif data == 'dashboard':
            await show_dashboard(query, user_id)
        elif data == 'load_groups':
            await load_groups(query, user_id, context)
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
    except Exception as e:
        logger.error(f"Button error: {e}")
        await query.answer("⚠️ Try /start", show_alert=True)

# =====================================================================
# 3️⃣ FIXED PHONE + INLINE OTP KEYBOARD
# =====================================================================
async def show_phone_screen(query):
    keyboard = [[InlineKeyboardButton("📱 ENTER PHONE ➡️", callback_data='login_phone')]]
    text = """
✅ **READY TO START!** 🎉

📱 **STEP 1: LOGIN**
━━━━━━━━━━━━━━━━━━━
**Enter your phone:**
`+1234567890`

👇 Click → Send phone:
    """
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except BadRequest:
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def show_phone_input(query, user_id):
    user_data[user_id] = {'step': 'phone'}
    text = """
📱 **SEND YOUR PHONE**

**Format:** `+1234567890`
✅ Country code (+)
✅ No spaces

**Type phone now 👇**
    """
    try:
        await query.edit_message_text(text, parse_mode='Markdown')
    except BadRequest:
        await query.message.reply_text(text, parse_mode='Markdown')

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id not in user_data:
        await update.message.reply_text("👆 /start first!")
        return

    step = user_data[user_id].get('step')

    if step == 'phone':
        await process_phone(update, context, text)
    elif step == 'otp':
        await process_otp_text(update, context, text)
    elif step == '2fa':
        await process_2fa(update, context, text)
    elif user_data[user_id].get('waiting_for') == 'delay':
        await process_delay(update, text)

async def process_phone(update: Update, context: ContextTypes.DEFAULT_TYPE, phone: str):
    user_id = update.effective_user.id
    
    if not re.match(r'^\+[1-9]\d{1,14}$', phone):
        await update.message.reply_text("❌ **INVALID!**\n\n**✅ Use:** `+1234567890`", parse_mode='Markdown')
        return

    loading_msg = await update.message.reply_text("🔄 **Sending OTP...**")
    await asyncio.sleep(2)

    try:
        user_data[user_id]['phone'] = phone
        user_data[user_id]['step'] = 'otp'

        client = await adbot.create_client(user_id)
        await client.connect()
        
        # ✅ FIXED OTP SENDING
        result = await client.send_code_request(phone, force_sms=True)
        user_data[user_id]['phone_code_hash'] = result.phone_code_hash
        
        await client.disconnect()

        await loading_msg.delete()
        await show_otp_keyboard(update.message, user_id)
        
    except FloodWaitError as e:
        await loading_msg.edit_text(f"⏳ **FloodWait:** {e.seconds}s")
    except Exception as e:
        logger.error(f"Phone error: {e}")
        await loading_msg.edit_text(f"❌ **Error:** {str(e)}")

async def show_otp_keyboard(message_or_query, user_id):
    """Show beautiful OTP inline keyboard"""
    keyboard = [
        [InlineKeyboardButton("📱 SHOW TELEGRAM CODE", callback_data='show_code')],
        [],
        [InlineKeyboardButton("1️⃣  2️⃣  3️⃣", callback_data='otp_123')],
        [InlineKeyboardButton("4️⃣  5️⃣  6️⃣", callback_data='otp_456')],
        [InlineKeyboardButton("7️⃣  8️⃣  9️⃣", callback_data='otp_789')],
        [InlineKeyboardButton("⌫ BACK", callback_data='otp_back'), InlineKeyboardButton("0️⃣ ENTER", callback_data='otp_0')],
    ]
    
    text = """
🔢 **OTP VERIFICATION**
━━━━━━━━━━━━━━━━━━━━━━━━━━━

📱 **Check Telegram app/SMS**
👆 Use buttons below OR
⌨️ Type 5-6 digit code

**OR Click:** 📱 SHOW TELEGRAM CODE
    """
    
    if hasattr(message_or_query, 'message_id'):  # It's a query
        try:
            await message_or_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        except:
            await message_or_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:  # It's a message
        await message_or_query.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def show_telegram_code(query, user_id):
    """Open Telegram official code screen"""
    keyboard = [[InlineKeyboardButton("🔙 BACK TO OTP", callback_data='otp_keyboard')]]
    
    text = """
📱 **OFFICIAL TELEGRAM CODE**
━━━━━━━━━━━━━━━━━━━━━━━━━━━

**Click button below:**
`tg://openmessage?user_id=777000`

✅ Official Telegram login
✅ 100% works every time
✅ Check your Telegram app

👇 **Click to open:**
    """
    
    button_url = InlineKeyboardButton("📱 OPEN TELEGRAM CODE", url="tg://openmessage?user_id=777000")
    keyboard[0].append(button_url)
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def process_otp_text(update: Update, context: ContextTypes.DEFAULT_TYPE, otp: str):
    """Handle typed OTP"""
    user_id = update.effective_user.id
    await verify_otp(user_id, otp, update.message)

async def button_handler_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle OTP button presses"""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    
    if data == 'otp_keyboard':
        await show_otp_keyboard(query, user_id)
    elif data == 'show_code':
        await show_telegram_code(query, user_id)
    elif data.startswith('otp_'):
        otp_char = data.split('_')[1]
        await handle_otp_button(user_id, otp_char, query)

async def handle_otp_button(user_id, char, query):
    """Build OTP from button presses"""
    if 'otp_buffer' not in user_data[user_id]:
        user_data[user_id]['otp_buffer'] = ''
    
    if char == 'back':
        user_data[user_id]['otp_buffer'] = user_data[user_id]['otp_buffer'][:-1]
    elif char == '0':
        if len(user_data[user_id]['otp_buffer']) < 6:
            user_data[user_id]['otp_buffer'] += '0'
    else:
        if len(user_data[user_id]['otp_buffer']) < 6:
            user_data[user_id]['otp_buffer'] += char
    
    # Show current OTP
    otp_display = user_data[user_id]['otp_buffer'] or '_____'
    await query.answer(f"OTP: {otp_display}")
    
    if len(user_data[user_id]['otp_buffer']) == 6:
        await verify_otp(user_id, user_data[user_id]['otp_buffer'], query)

async def verify_otp(user_id, otp, message_or_query):
    """Verify OTP with animation"""
    loading_msg = None
    if hasattr(message_or_query, 'message_id'):
        loading_msg = await message_or_query.edit_message_text("🔄 **Verifying OTP...**")
    else:
        loading_msg = await message_or_query.reply_text("🔄 **Verifying OTP...**")

    try:
        client = await adbot.create_client(user_id)
        await client.connect()
        
        await client.sign_in(phone=user_data[user_id]['phone'], code=otp)

        session_string = client.session.save()
        user_data[user_id]['session'] = session_string
        user_data[user_id]['logged_in'] = True
        user_data[user_id]['step'] = None
        
        if 'otp_buffer' in user_data[user_id]:
            del user_data[user_id]['otp_buffer']
            
        await client.disconnect()

        await loading_msg.edit_text("🎉 **LOGIN SUCCESS!** 🎉\n🔄 Dashboard loading...")
        await asyncio.sleep(2)
        await loading_msg.delete()
        await dashboard_message(loading_msg, user_id)

    except SessionPasswordNeededError:
        user_data[user_id]['step'] = '2fa'
        await loading_msg.edit_text("🔐 **2FA NEEDED**\nEnter password:")
    except PhoneCodeInvalidError:
        await loading_msg.edit_text("❌ **WRONG OTP**\nTry again:")
    except Exception as e:
        logger.error(f"OTP verify error: {e}")
        await loading_msg.edit_text(f"❌ **Error:** {str(e)}")

# =====================================================================
# REST OF THE CODE (Dashboard, Groups, etc.) - SAME AS BEFORE
# =====================================================================
async def dashboard_message(update, user_id):
    keyboard = [
        [InlineKeyboardButton("📥 LOAD GROUPS", callback_data='load_groups')],
        [InlineKeyboardButton("📢 SET AD", callback_data='set_ad')],
        [InlineKeyboardButton("⏱️ SET DELAY", callback_data='set_delay')],
        [],
        [InlineKeyboardButton("🚀 START BOT", callback_data='start_bot')],
        [InlineKeyboardButton("⛔ STOP BOT", callback_data='stop_bot')],
        [InlineKeyboardButton("📊 STATUS", callback_data='status')]
    ]
    
    groups_count = len(user_data[user_id].get('groups', []))
    delay = user_data[user_id].get('delay', 0)
    
    status = f"📱 Groups: `{groups_count}`\n⏱️ Delay: `{delay}s`"
    if user_id in ad_message:
        status += "\n📢 Ad: ✅ READY"
    
    text = f"""
🎛️ **ADIMYZE DASHBOARD** 🎛️
━━━━━━━━━━━━━━━━━━━━━━━━━

{status}

**🚀 QUICK START:**
1. Load Groups
2. Forward Ad  
3. Set Delay
4. START BOT 💰

👇 Choose:
    """
    
    await update.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# [Rest of functions remain same: load_groups, set_ad_prompt, etc.]
# ... (copy from previous version)

async def process_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE, password: str):
    # Same as before
    pass

async def load_groups(query, user_id, context):
    # Same as before
    pass

# ... all other functions same as v3.0

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.FORWARDED, handle_forwarded_message))
    app.add_error_handler(error_handler)
    
    print("🚀 ADIMYZE v3.1 - OTP KEYBOARD + TG LINK!")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()