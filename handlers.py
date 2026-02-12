from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from login_manager import generate_otp, verify_otp

user_agreement = {}
user_logged_in = {}
user_otp_data = {}

# Welcome message and policy agreement
def start(update, context):
    user = update.message.from_user
    user_id = user.id

    if user_id not in user_agreement:
        policy_text = (
            "✨ Welcome to Adimyze Bot ✨\n\n"
            "🔒 Connection Required\n"
            "To access all premium features, please connect your Telegram account first.\n\n"
            "📦 Your Current Plan: Free\n"
            "⚡ Ad Broadcasting - Smart Delays\n\n"
            "👑 Admin: @Sharibraza\n\n"
            "If you agree to these terms, reply with /agree to start receiving ads."
        )
        update.message.reply_text(policy_text)
    else:
        send_main_menu(update)

# Handle the /agree command
def agree(update, context):
    user = update.message.from_user
    user_id = user.id
    user_agreement[user_id] = True
    update.message.reply_text("Thank you for agreeing to our policy! Let's proceed with login.")
    update.message.reply_text("Please enter your phone number (with country code), e.g., +11234567890.")

# Handle phone number input
def phone_number_input(update, context):
    user = update.message.from_user
    user_id = user.id
    phone_number = update.message.text.strip()
    otp = generate_otp(phone_number)
    user_otp_data[user_id] = {'phone': phone_number, 'otp': otp, 'attempts': 0}
    
    otp_keyboard = [
        [InlineKeyboardButton("Enter OTP", callback_data='otp_request')],
        [InlineKeyboardButton("Cancel", callback_data='cancel_request')]
    ]
    reply_markup = InlineKeyboardMarkup(otp_keyboard)
    update.message.reply_text(f"OTP has been sent to {phone_number}. Please press 'Enter OTP' to input the OTP.", reply_markup=reply_markup)

# Handle OTP input via inline button
def otp_input(update, context):
    query = update.callback_query
    user = query.from_user
    user_id = user.id

    if user_id in user_otp_data:
        user_otp_data[user_id]['attempts'] += 1
        max_attempts = 3
        if user_otp_data[user_id]['attempts'] <= max_attempts:
            query.answer()
            query.edit_message_text(text=f"Attempt {user_otp_data[user_id]['attempts']} of {max_attempts}. Please enter your OTP:")
            return
        else:
            query.edit_message_text(text="❌ Maximum OTP attempts reached. Please restart the process using /start.")
            return

# Cancel OTP process
def cancel_process(update, context):
    query = update.callback_query
    query.answer()
    
    user_id = query.from_user.id
    if user_id in user_otp_data:
        del user_otp_data[user_id]
    
    query.edit_message_text("❌ OTP process has been cancelled. Please start again using /start.")
    update.message.reply_text("You can start the process again by typing /start.")

# Handle OTP verification
def handle_otp_input(update, context):
    user = update.message.from_user
    user_id = user.id
    entered_otp = update.message.text.strip()

    if user_id in user_otp_data:
        otp_data = user_otp_data[user_id]
        if entered_otp == otp_data['otp']:
            user_logged_in[user_id] = True
            del user_otp_data[user_id]
            update.message.reply_text("✅ Login successful! You are now logged in.")
            send_main_menu(update)
        else:
            update.message.reply_text("❌ Incorrect OTP. Please try again.")
    else:
        update.message.reply_text("⚠️ Session expired or invalid. Please start again using /start.")

# Main Menu after successful login
def send_main_menu(update):
    user = update.message.from_user
    user_id = user.id

    if user_id not in user_logged_in:
        user_logged_in[user_id] = True

    home_keyboard = [
        [InlineKeyboardButton("👤 My Account", callback_data='account')],
        [InlineKeyboardButton("🎯 Manage Targets", callback_data='targets')],
        [InlineKeyboardButton("🚀 Start Ads", callback_data='start_ads')],
        [InlineKeyboardButton("🛑 Stop Ads", callback_data='stop_ads')],
        [InlineKeyboardButton("👤 My Details", callback_data='my_details')],
        [InlineKeyboardButton("⚙️ More Features", callback_data='more_features')]
    ]
    reply_markup = InlineKeyboardMarkup(home_keyboard)
    update.message.reply_text("Welcome to Adimyze Bot! Choose an option below:", reply_markup=reply_markup)

# Handle the callback data for menu options
def button_click(update, context):
    query = update.callback_query
    query.answer()
    
    data = query.data
    if data == 'account':
        query.edit_message_text(text="Account settings are here.")
    elif data == 'targets':
        query.edit_message_text(text="Manage your targets here.")
    elif data == 'start_ads':
        query.edit_message_text(text="Ads will start soon. Let's get your ads running!")
    elif data == 'stop_ads':
        query.edit_message_text(text="Ads have been stopped. We can start again anytime!")
    elif data == 'my_details':
        query.edit_message_text(text="Here are your personal details.")
    elif data == 'more_features':
        query.edit_message_text(text="More features will be available soon. Stay tuned!")