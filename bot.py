from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters
import logging
from config import BOT_TOKEN
from handlers import start, agree, phone_number_input, handle_otp_input, otp_input, cancel_process, button_click

# Set up logging
logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.INFO)

# Telegram Bot Token
bot = Bot(token=BOT_TOKEN)

# Set up the bot with handlers
updater = Updater(token=BOT_TOKEN, use_context=True)
dp = updater.dispatcher

# Command Handlers
dp.add_handler(CommandHandler("start", start))
dp.add_handler(CommandHandler("agree", agree))

# Handle phone number and OTP input
dp.add_handler(MessageHandler(Filters.regex(r'^\+?[1-9]\d{1,14}$'), phone_number_input))  # Regex to match phone numbers
dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_otp_input))  # Handle OTP input

# Handle the callback from the inline keyboard button
dp.add_handler(CallbackQueryHandler(otp_input, pattern='^otp_request$'))
dp.add_handler(CallbackQueryHandler(cancel_process, pattern='^cancel_request$'))  # Cancel process
dp.add_handler(CallbackQueryHandler(button_click))

# Start the bot
updater.start_polling()