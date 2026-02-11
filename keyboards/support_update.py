# keyboards/support_update.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def support_menu():
    """Return the support menu keyboard"""
    keyboard = [
        [InlineKeyboardButton("Contact Support", callback_data='contact_support')],
        [InlineKeyboardButton("Back", callback_data='back_to_main')],
    ]
    return InlineKeyboardMarkup(keyboard)

def update_menu():
    """Return the update menu keyboard"""
    keyboard = [
        [InlineKeyboardButton("Current Version", callback_data='current_version')],
        [InlineKeyboardButton("Back", callback_data='back_to_main')],
    ]
    return InlineKeyboardMarkup(keyboard)