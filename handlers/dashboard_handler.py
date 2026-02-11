# handlers/dashboard_handler.py
from telegram import Update
from telegram.ext import CallbackContext
from keyboards.dashboard_menu import dashboard_menu
from database import get_all_accounts, get_ad_message, get_cycle_interval, get_ad_status

def dashboard(update: Update, context: CallbackContext):
    """Show the dashboard menu with actions"""
    user = update.callback_query.from_user

    # Get dynamic data (accounts count, ad message, cycle interval, and ad status)
    hosted_accounts = get_all_accounts()  # This should return a list of accounts or their count
    ad_message = get_ad_message()  # Fetch ad message from the database
    cycle_interval = get_cycle_interval()  # Fetch cycle interval from the database
    ad_status = get_ad_status()  # Fetch ad status from the database

    # Prepare the dashboard message
    dashboard_message = f"""
    • Hosted Accounts: {len(hosted_accounts)}/5
    • Ad Message: {ad_message if ad_message else 'Not Set'}
    • Cycle Interval: {cycle_interval}s
    • Advertising Status: {ad_status}
    
    Choose an action below:
    """
    
    # Show the dashboard with options
    update.callback_query.edit_message_text(text=dashboard_message, reply_markup=dashboard_menu())

def back_to_main(update: Update, context: CallbackContext):
    """Go back to the main menu"""
    from handlers.start_handler import start
    start(update, context)
