# keyboards/main_menu.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def main_menu():
    """Return the main menu keyboard"""
    keyboard = [
        [InlineKeyboardButton("Dashboard", callback_data='dashboard')],
        [InlineKeyboardButton("Support", callback_data='support')],
        [InlineKeyboardButton("Update", callback_data='update')],
    ]
    return InlineKeyboardMarkup(keyboard)