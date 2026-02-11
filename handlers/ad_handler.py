# handlers/ad_handler.py
from telegram import Update
from telegram.ext import CallbackContext
from database import set_ad_message, start_ads, stop_ads

def set_ad_message(update: Update, context: CallbackContext):
    """Handle setting the ad message"""
    update.callback_query.edit_message_text(text="Please send the ad message you want to set.")
    ad_message = update.message.text  # Capturing the message
    set_ad_message(ad_message)
    update.message.reply_text(f"Ad message has been set:\n{ad_message}")

def start_ad_broadcast(update: Update, context: CallbackContext):
    """Handle starting the ad broadcast"""
    start_ads()
    update.callback_query.edit_message_text(text="Ad broadcasting has started!")

def stop_ad_broadcast(update: Update, context: CallbackContext):
    """Handle stopping the ad broadcast"""
    stop_ads()
    update.callback_query.edit_message_text(text="Ad broadcasting has been paused.")
