# keyboards/dashboard_menu.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def dashboard_menu():
    """Return the dashboard menu keyboard"""
    keyboard = [
        [InlineKeyboardButton("Add Accounts", callback_data='add_accounts')],
        [InlineKeyboardButton("My Accounts", callback_data='my_accounts')],
        [InlineKeyboardButton("Set Ad Message", callback_data='set_ad_message')],
        [InlineKeyboardButton("Set Time Interval", callback_data='set_time_interval')],
        [InlineKeyboardButton("Start Ads", callback_data='start_ads')],
        [InlineKeyboardButton("Stop Ads", callback_data='stop_ads')],
        [InlineKeyboardButton("Delete Accounts", callback_data='delete_accounts')],
        [InlineKeyboardButton("Analytics", callback_data='analytics')],
        [InlineKeyboardButton("Auto Reply", callback_data='auto_reply')],
        [InlineKeyboardButton("Back", callback_data='back_to_main')],
    ]
    return InlineKeyboardMarkup(keyboard)