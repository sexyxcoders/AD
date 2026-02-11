# handlers/start_handler.py
from telegram import Update
from telegram.ext import CallbackContext
from keyboards.main_menu import main_menu

def start(update: Update, context: CallbackContext):
    """Handle the /start command"""
    user = update.message.from_user
    start_message = "Welcome to the bot! Choose an option below:"
    update.message.reply_text(start_message, reply_markup=main_menu())

# Register the /start command
from telegram.ext import CommandHandler

start_handler = CommandHandler('start', start)
