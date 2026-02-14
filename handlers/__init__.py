from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters
)

# Import individual handlers
from .start import start_command, navigation_handler
from .accounts import (
    account_callback_handler,
    phone_input_handler,
    account_deletion_handler
)
from .otp import otp_callback_handler, password_input_handler
from .ads import ad_callback_handler, ad_message_handler
from .delay import delay_callback_handler, custom_delay_handler
from .campaigns import campaign_callback_handler
from .analytics import analytics_callback_handler
from .features import feature_callback_handler
from .fallbacks import noop_callback_handler, unknown_message_handler, error_handler

def register_handlers(application):
    """
    Register all handlers with proper priority ordering:
    1. Command handlers
    2. Callback query handlers (specific to general)
    3. Message handlers (text inputs)
    4. Fallback/error handlers
    """
    # Command handlers
   