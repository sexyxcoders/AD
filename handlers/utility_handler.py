# handlers/utility_handler.py
from telegram import Update
from telegram.ext import CallbackContext
from database import set_cycle_interval, get_logs

def set_time_interval(update: Update, context: CallbackContext):
    """Handle setting the cycle interval"""
    update.callback_query.edit_message_text(text="Please set the cycle interval (in seconds).")
    interval = int(update.message.text)  # Capture the interval value
    set_cycle_interval(interval)
    update.message.reply_text(f"Cycle interval has been set to {interval} seconds.")

def view_logs(update: Update, context: CallbackContext):
    """Handle viewing logs"""
    logs = get_logs()  # Fetch logs from your database or system
    logs_message = "\n".join(logs)
    update.callback_query.edit_message_text(text=f"Logs:\n{logs_message}")
