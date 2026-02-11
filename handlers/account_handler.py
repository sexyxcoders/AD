# handlers/account_handler.py
from telegram import Update
from telegram.ext import CallbackContext
from database import save_account, delete_account, get_all_accounts

def add_account(update: Update, context: CallbackContext):
    """Handle adding a new account"""
    # Request the user for phone number or credentials
    update.callback_query.edit_message_text(text="Please send your phone number to add a new account.")

    # You can implement logic to capture the phone number and save the account to the database
    phone_number = update.message.text
    save_account(phone_number)
    update.message.reply_text(f"Account with phone number {phone_number} has been added.")

def delete_account(update: Update, context: CallbackContext):
    """Handle account deletion"""
    update.callback_query.edit_message_text(text="Please provide the account ID to delete.")
    # Capture account ID and delete the account
    account_id = update.message.text  # Assuming text contains account ID
    delete_account(account_id)
    update.message.reply_text(f"Account with ID {account_id} has been deleted.")

def view_accounts(update: Update, context: CallbackContext):
    """View all the hosted accounts"""
    accounts = get_all_accounts()
    accounts_message = "\n".join(accounts)
    update.callback_query.edit_message_text(text=f"Your hosted accounts:\n{accounts_message}")
