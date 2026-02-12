import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import BadRequest
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, FloodWaitError
import asyncio
import re
import random

# CONFIG
BOT_TOKEN = '8463982454:AAFXhclFtn5cCoJLZl3l-SwhPMk3ssv6J8o'
API_ID = 22657083
API_HASH = 'd6186691704bd901bdab275ceaab88f3'

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

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
            logger.error(f"Client error: {e}")
            raise

adbot = AdBot()

LOADING_MESSAGES = ["🔄 Processing...", "⏳ Please wait...", "⚡ Loading...", "🔥 Almost ready...", "✅ Done!"]

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

# =====================================================================
# 1. START COMMAND
# =====================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = [[InlineKeyboardButton("✅ START AD BOT ➡️", callback_data='accept_policy')]]
    text = """
🎯 **ADIMYZE PRO v4.0** 🎯

🔥 **AUTO AD MACHINE** 🔥
━━━━━━━━━━━━━━━━━━━━━━━━━━━
💎 Load 50+ groups
💎 Post images/videos/text
💎 Safe & automatic
💎 YOUR account only

👇 **Click START 💰**
    """
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# =====================================================================
# 2. BUTTON HANDLER
# =====================================================================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == 'accept_policy':
        await show_phone_screen(query)
    elif data == 'login_phone':
        await show_phone_input(query, user_id)
    elif data == 'otp_keyboard':
        await show_otp_keyboard(query, user_id)
    elif data == 'show_code':
        await show_telegram_code(query, user_id)
    elif data.startswith('otp_'):
        await handle_otp_button(user_id, data.split('_')[1], query)
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

# =====================================================================
# 3. PHONE AUTH FLOW
# =====================================================================
async def show_phone_screen(query):
    keyboard = [[InlineKeyboardButton("📱 ENTER PHONE ➡️", callback_data='login_phone')]]
    text = """
✅ **WELCOME!** 🎉

📱 **STEP 1: LOGIN**
━━━━━━━━━━━━━━━━━━━
Send your phone:
`+1234567890`

👇 Click → Type phone:
    """
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except:
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def show_phone_input(query, user_id):
    user_data[user_id] = {'step': 'phone'}
    text = """
📱 **SEND PHONE NUMBER**

**Format:** `+1234567890`
✅ +Country code
✅ No spaces

**Type now 👇**
    """
    try:
        await query.edit_message_text(text, parse_mode='Markdown')
    except:
        await query.message.reply_text(text, parse_mode='Markdown')

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id not in user_data:
        return

    step = user_data[user_id].get('step')

    if step == 'phone':
        await process_phone(update, context, text)
    elif step == 'otp':
        await verify_otp(user_id, text, update.message)
    elif step == '2fa':
        await process_2fa(update, context, text)
    elif user_data[user_id].get('waiting_for') == 'delay':
        await process_delay(update, text)

async def process_phone(update: Update, context: ContextTypes.DEFAULT_TYPE, phone: str):
    user_id = update.effective_user.id
    
    if not re.match(r'^\+[1-9]\d{1,14}$', phone):
        await update.message.reply_text("❌ **WRONG FORMAT**\n`+1234567890`", parse_mode='Markdown')
        return

    await update.message.reply_text("🔄 **Sending OTP...**")
    await asyncio.sleep(2)

    try:
        user_data[user_id]['phone'] = phone
        user_data[user_id]['step'] = 'otp'

        client = await adbot.create_client(user_id)
        await client.connect()
        result = await client.send_code_request(phone, force_sms=True)
        user_data[user_id]['phone_code_hash'] = result.phone_code_hash
        await client.disconnect()

        await show_otp_keyboard(update.message, user_id)
        
    except Exception as e:
        logger.error(f"Phone error: {e}")
        await update.message.reply_text(f"❌ **Error:** {str(e)}")

async def show_otp_keyboard(message_or_query, user_id):
    keyboard = [
        [InlineKeyboardButton("📱 SHOW TG CODE", callback_data='show_code')],
        [],
        [InlineKeyboardButton("1️⃣  2️⃣  3️⃣", callback_data='otp_123')],
        [InlineKeyboardButton("4️⃣  5️⃣  6️⃣", callback_data='otp_456')],
        [InlineKeyboardButton("7️⃣  8️⃣  9️⃣", callback_data='otp_789')],
        [InlineKeyboardButton("⌫", callback_data='otp_back'), InlineKeyboardButton("0️⃣ ✅", callback_data='otp_0')],
    ]
    
    text = """
🔢 **ENTER OTP CODE**
━━━━━━━━━━━━━━━━━━━

📱 Check Telegram/SMS
👆 Click numbers OR
⌨️ Type code

**📱 SHOW TG CODE = 100% works**
    """
    
    if hasattr(message_or_query, 'reply_text'):
        await message_or_query.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        try:
            await message_or_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        except:
            await message_or_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def show_telegram_code(query, user_id):
    keyboard = [[InlineKeyboardButton("🔙 BACK TO OTP", callback_data='otp_keyboard')]]
    text = """
📱 **OFFICIAL TELEGRAM**
━━━━━━━━━━━━━━━━━━━

**Click = Instant OTP:**
`tg://openmessage?user_id=777000`

✅ 100% Guaranteed code
✅ Opens Telegram app
✅ Copy & paste code

👇 **OPEN TG:**
    """
    url_btn = InlineKeyboardButton("📱 TELEGRAM LOGIN", url="tg://openmessage?user_id=777000")
    keyboard[0].append(url_btn)
    
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def handle_otp_button(user_id, char, query):
    if 'otp_buffer' not in user_data[user_id]:
        user_data[user_id]['otp_buffer'] = ''
    
    if char == 'back':
        user_data[user_id]['otp_buffer'] = user_data[user_id]['otp_buffer'][:-1]
    else:
        if len(user_data[user_id]['otp_buffer']) < 6:
            user_data[user_id]['otp_buffer'] += char
    
    otp_display = user_data[user_id]['otp_buffer'] or '______'
    await query.answer(f"OTP: {otp_display}")
    
    if len(user_data[user_id]['otp_buffer']) == 6:
        await verify_otp(user_id, user_data[user_id]['otp_buffer'], query)

async def verify_otp(user_id, otp, message_or_query):
    loading_msg = None
    try:
        if hasattr(message_or_query, 'reply_text'):
            loading_msg = await message_or_query.reply_text("🔄 **Checking OTP...**")
        else:
            loading_msg = await message_or_query.message.reply_text("🔄 **Checking OTP...**")
    except:
        loading_msg = await message_or_query.reply_text("🔄 **Checking OTP...**")

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

        await loading_msg.edit_text("🎉 **LOGIN SUCCESS!** 🎉")
        await asyncio.sleep(1)
        await show_dashboard(loading_msg, user_id)

    except SessionPasswordNeededError:
        user_data[user_id]['step'] = '2fa'
        await loading_msg.edit_text("🔐 **2FA PASSWORD:**\nSend password:")
    except PhoneCodeInvalidError:
        await loading_msg.edit_text("❌ **WRONG OTP**\nTry again:")
    except Exception as e:
        logger.error(f"OTP error: {e}")
        await loading_msg.edit_text(f"❌ **Error:** {str(e)}")

async def process_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE, password: str):
    user_id = update.effective_user.id
    loading_msg = await update.message.reply_text("🔓 **Checking 2FA...**")

    try:
        client = await adbot.create_client(user_id, user_data[user_id]['session'])
        await client.connect()
        await client.sign_in(password=password)
        user_data[user_id]['logged_in'] = True
        user_data[user_id]['step'] = None
        await client.disconnect()

        await loading_msg.edit_text("🔓 **2FA OK!** 🎉")
        await show_dashboard(loading_msg, user_id)

    except Exception as e:
        await loading_msg.edit_text(f"❌ **Wrong 2FA:** {str(e)}")

# =====================================================================
# 4. DASHBOARD & FEATURES
# =====================================================================
async def show_dashboard(query_or_msg, user_id):
    keyboard = [
        [InlineKeyboardButton("📥 LOAD GROUPS", callback_data='load_groups')],
        [InlineKeyboardButton("📢 SET AD", callback_data='set_ad')],
        [InlineKeyboardButton("⏱️ SET DELAY", callback_data='set_delay')],
        [],
        [InlineKeyboardButton("🚀 START", callback_data='start_bot')],
        [InlineKeyboardButton("⛔ STOP", callback_data='stop_bot')],
        [InlineKeyboardButton("📊 STATUS", callback_data='status')]
    ]
    
    groups = len(user_data[user_id].get('groups', []))
    delay = user_data[user_id].get('delay', 0)
    ad_ready = user_id in ad_message
    
    text = f"""
🎛️ **ADIMYZE DASHBOARD**
━━━━━━━━━━━━━━━━━━━━━━━━━

📱 Groups: `{groups}`
⏱️ Delay: `{delay}s`
📢 Ad: `{'✅ YES' if ad_ready else '❌ NO'}`
🤖 Bot: `{'🟢 ON' if user_id in running_users else '🔴 OFF'}`

**👇 Choose action:**
    """
    
    try:
        if hasattr(query_or_msg, 'edit_message_text'):
            await query_or_msg.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else:
            await query_or_msg.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except:
        await query_or_msg.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def load_groups(query, user_id, context):
    await query.answer("📥 Loading...")
    try:
        client = await adbot.create_client(user_id, user_data[user_id]['session'])
        await client.start()
        
        groups = []
        async for dialog in client.iter_dialogs():
            if (dialog.is_group or dialog.is_channel) and dialog.name:
                groups.append({'id': dialog.id, 'name': dialog.name[:30]})
        
        user_data[user_id]['groups'] = groups[:50]
        await client.disconnect()

        text = f"✅ **{len(groups)} GROUPS LOADED**\n👆 Back to dashboard"
        await query.edit_message_text(text, parse_mode='Markdown')
        
    except Exception as e:
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)

async def set_ad_prompt(query, user_id):
    user_data[user_id]['waiting_ad'] = True
    text = "📢 **FORWARD YOUR AD**\nFrom Saved Messages 👇"
    await query.edit_message_text(text, parse_mode='Markdown')

async def handle_forwarded_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_data[user_id].get('waiting_ad'):
        msg = update.message
        ad_message[user_id] = {
            'chat_id': msg.forward_from_chat.id if msg.forward_from_chat else msg.chat.id,
            'msg_id': msg.forward_from_message_id or msg.message_id
        }
        del user_data[user_id]['waiting_ad']
        await update.message.reply_text("✅ **AD SAVED!** 🎉\n👆 Dashboard")
        await show_dashboard(update.message, user_id)

async def set_delay_prompt(query, user_id):
    user_data[user_id]['waiting_for'] = 'delay'
    text = "⏱️ **DELAY (seconds):**\n`30` `60` `300` `600`"
    await query.edit_message_text(text, parse_mode='Markdown')

async def process_delay(update: Update, text: str):
    user_id = update.effective_user.id
    try:
        delay = int(text)
        if delay < 10:
            await update.message.reply_text("❌ **Min 10s**")
            return
        user_data[user_id]['delay'] = delay
        del user_data[user_id]['waiting_for']
        await update.message.reply_text(f"✅ **Delay: {delay}s**")
        await show_dashboard(update.message, user_id)
    except:
        await update.message.reply_text("❌ **Number only!**")

async def start_bot(query, user_id):
    if not all([user_data[user_id].get(x) for x in ['logged_in', 'groups', 'delay']]):
        return await query.answer("❌ **Setup first!**", show_alert=True)
    if user_id not in ad_message:
        return await query.answer("❌ **Set AD first!**", show_alert=True)

    running_users[user_id] = True
    asyncio.create_task(ad_loop(user_id))
    text = f"""
🚀 **BOT STARTED!** 💰
Groups: {len(user_data[user_id]['groups'])}
Delay: {user_data[user_id]['delay']}s
🟢 **RUNNING**
    """
    await query.edit_message_text(text, parse_mode='Markdown')

async def ad_loop(user_id):
    while running_users.get(user_id):
        try:
            client = await adbot.create_client(user_id, user_data[user_id]['session'])
            await client.start()
            for group in user_data[user_id]['groups']:
                if not running_users.get(user_id):
                    break
                try:
                    await client.forward_messages(group['id'], ad_message[user_id]['chat_id'], ad_message[user_id]['msg_id'])
                    await asyncio.sleep(user_data[user_id]['delay'])
                except:
                    continue
            await client.disconnect()
            await asyncio.sleep(300)
        except:
            await asyncio.sleep(60)

async def stop_bot(query, user_id):
    running_users[user_id] = False
    await query.edit_message_text("⛔ **BOT STOPPED** ✅", parse_mode='Markdown')

async def show_status(query, user_id):
    groups = len(user_data[user_id].get('groups', []))
    text = f"""
📊 **STATUS**
Groups: {groups}
Bot: {'🟢 ON' if user_id in running_users else '🔴 OFF'}
    """
    await query.edit_message_text(text, parse_mode='Markdown')

# =====================================================================
# MAIN
# =====================================================================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.FORWARDED, handle_forwarded_message))
    app.add_error_handler(error_handler)
    
    print("🚀 ADIMYZE v4.0 - FULLY WORKING!")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()