# handlers/support_update.py
from telegram import Update
from telegram.ext import CallbackContext

def show_support(update: Update, context: CallbackContext):
    """Show support contact details"""
    update.callback_query.edit_message_text(text="Support: For assistance, please contact @SupportUser.")

def show_update(update: Update, context: CallbackContext):
    """Show update information"""
    update.callback_query.edit_message_text(text="Update: Version 1.0.0 - Initial release.")
