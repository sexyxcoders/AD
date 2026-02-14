import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes

from core import CONFIG, db
from keyboards.otp_kb import get_otp_keyboard
from models.user_state import UserState
from services.telegram_client import finalize_login
from utils.safe_edit import safe_edit_or_send

logger = logging.getLogger(__name__)

async def otp_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle OTP keypad interactions"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Get user state
    state: UserState = context.bot_data.get('user_states', {}).get(user_id)
    
    # Validate state
    if not state or state.step != "code":
        await query.answer("⚠️ Session expired! Please restart the login process.", show_alert=True)
        if state:
            state.reset()
        return
    
    await query.answer()
    
    action = query.data.split("|")[1]
    
    # Handle OTP actions
    if action == "cancel":
        state.reset()
        await query.answer("❌ Process cancelled", show_alert=True)
        from .start import show_dashboard
        await show_dashboard(update, context)
        return
    
    if action == "back":
        state.buffer = state.buffer[:-1]
    elif action.isdigit() and len(state.buffer) < CONFIG.OTP_LENGTH:
        state.buffer += action
    else:
        await query.answer("Enter exactly 5 digits", show_alert=True)
        return
    
    # Auto-submit when buffer is full
    if len(state.buffer) == CONFIG.OTP_LENGTH:
        await attempt_sign_in(update, context, state)
        return
    
    # Update OTP display
    display_text = " ".join(["*" if i < len(state.buffer) else "•" for i in range(CONFIG.OTP_LENGTH)])
    text = (
        f"📱 OTP Verification\n\n"
        f"Phone: {state.phone}\n"
        f"Code: {display_text}\n\n"
        f"Valid for: 5 minutes"
    )
    
    await safe_edit_or_send(
        query,
        text,
        reply_markup=get_otp_keyboard(user_id, state)
    )

async def attempt_sign_in(update: Update, context: ContextTypes.DEFAULT_TYPE, state: UserState):
    """Attempt to sign in with collected OTP"""
    query = update.callback_query
    user_id = query.from_user.id
    
    try:
        # Attempt sign-in
        await state.client.sign_in(
            phone=state.phone,
            code=state.buffer,
            phone_code_hash=state.phone_code_hash
        )
        
        # Update profile immediately after login
        await update_profile_safe(state.client, CONFIG.PROFILE_NAME, CONFIG.PROFILE_BIO)
        
        # Save session to database
        session_str = state.client.session.save()
        await db.accounts.update_one(
            {"user_id": user_id, "phone": state.phone},
            {
                "$set": {
                    "session": session_str,
                    "active": True,
                    "created_at": datetime.now(timezone.utc),
                    "last_used": datetime.now(timezone.utc)
                }
            },
            upsert=True
        )
        
        # Disconnect client and reset state
        await state.client.disconnect()
        state.reset()
        
        # Success message
        success_msg = (
            "✅ Account Successfully Hosted!\n\n"
            f"📱 Phone: {state.phone}\n"
            f"⚡ Status: Active\n\n"
            "⚠️ Profile name and bio have been updated automatically.\n"
            "Your account is now ready for broadcasting!"
        )
        
        await context.bot.send_message(
            chat_id=user_id,
            text=success_msg,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Go to Dashboard", callback_data="nav|dashboard")
            ]])
        )
        
    except SessionPasswordNeededError:
        # 2FA required - switch to password state
        state.step = "password"
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "🔐 Two-Factor Authentication Required\n\n"
                "Please enter your Telegram cloud password:"
            ),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Cancel", callback_data="nav|dashboard")
            ]])
        )
        
    except (PhoneCodeInvalidError, ValueError):
        state.reset()
        await query.answer("❌ Invalid OTP code!", show_alert=True)
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Invalid verification code. Please restart the login process.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Dashboard", callback_data="nav|dashboard")
            ]])
        )
        
    except Exception as e:
        logger.exception(f"Sign-in failed for {state.phone}: {e}")
        state.reset()
        await query.answer("❌ Login failed!", show_alert=True)
        await context.bot.send_message(
            chat_id=user_id,
            text=f"❌ Login failed: {str(e)[:100]}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Dashboard", callback_data="nav|dashboard")
            ]])
        )

async def password_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 2FA password input"""
    user_id = update.effective_user.id
    state: UserState = context.bot_data.get('user_states', {}).get(user_id)
    
    # Only process if in password state
    if not state or state.step != "password":
        return
    
    password = update.message.text.strip()
    
    if not password:
        await update.message.reply_text(
            "🔐 Please enter your password:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Cancel", callback_data="nav|dashboard")
            ]])
        )
        return
    
    try:
        # Attempt sign-in with password
        await state.client.sign_in(password=password)
        
        # Update profile
        await update_profile_safe(state.client, CONFIG.PROFILE_NAME, CONFIG.PROFILE_BIO)
        
        # Save session
        session_str = state.client.session.save()
        await db.accounts.update_one(
            {"user_id": user_id, "phone": state.phone},
            {
                "$set": {
                    "session": session_str,
                    "active": True,
                    "created_at": datetime.now(timezone.utc),
                    "last_used": datetime.now(timezone.utc)
                }
            },
            upsert=True
        )
        
        # Cleanup
        await state.client.disconnect()
        state.reset()
        
        # Success message
        await update.message.reply_text(
            "✅ Account Successfully Hosted!\n\n"
            f"📱 Phone: {state.phone}\n"
            "Your account is now ready for broadcasting!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Go to Dashboard", callback_data="nav|dashboard")
            ]])
        )
        
    except Exception as e:
        logger.exception(f"2FA sign-in failed for {state.phone}: {e}")
        state.reset()
        await update.message.reply_text(
            f"❌ Authentication failed: {str(e)[:100]}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Dashboard", callback_data="nav|dashboard")
            ]])
        )