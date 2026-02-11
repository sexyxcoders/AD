# bot.py
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler
from handlers.start_handler import start_handler
from handlers.dashboard_handler import dashboard_handler
from handlers.account_handler import account_handler
from handlers.ad_handler import ad_handler
from handlers.utility_handler import utility_handler
from handlers.support_update import support_handler, update_handler

# Set up the Updater and Dispatcher
updater = Updater("YOUR_BOT_API_TOKEN", use_context=True)
dp = updater.dispatcher

# Register Handlers
dp.add_handler(start_handler)          # /start command
dp.add_handler(dashboard_handler)      # Dashboard button actions
dp.add_handler(account_handler)        # Account-related actions
dp.add_handler(ad_handler)             # Ad-related actions (setting, starting, stopping)
dp.add_handler(utility_handler)        # Utility actions (setting time interval, viewing logs)
dp.add_handler(support_handler)        # Support button
dp.add_handler(update_handler)         # Update button

# Start the bot
updater.start_polling()
updater.idle()
