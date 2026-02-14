import re
import logging
from datetime import datetime, timezone
from typing import Optional
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    FloodWaitError,
    PhoneNumberInvalidError,
    PhoneNumberBannedError,
    PhoneNumberFloodError
)

from core import CONFIG, API_ID, API_HASH, db
from keyboards.accounts_kb import (
    get_accounts_keyboard,
    get_account_detail_keyboard,
    get_delete_confirmation_keyboard
)
from keyboards.otp_kb import get_otp_keyboard
from models.user_state import UserState
from utils.safe_edit import safe_edit_or_send
from services.telegram_client import update_profile_safe

logger = logging.getLogger(__name__)

async def account_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main account operation router"""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split("|")
    action = parts[1]
    
    handlers = {
        "add": initiate_account_addition,
        "list": show_account_list,
        "detail": show_account_detail,
        "delete": show_delete_confirmation,
        "del": show_delete_overview  # Bulk delete entry point
    }
    
    handler = handlers.get(action)
    if handler:
        await handler(update, context, parts)
    else:
        await query.answer("Unknown account action", show_alert=True)

async def initiate_account_addition(update: Update, context: ContextTypes.DEFAULT_TYPE, parts):
    """Start the account addition flow"""
    user_id = update.effective_user.id
    
    # Initialize user state
    context.bot_data.setdefault('user_states', {})
    context.bot_data['user_states'][user_id] = UserState(step="phone")
    
    text = (
        "📱 HOST NEW ACCOUNT\n\n"
        "🔒 Secure Account Hosting\n\n"
        "Please enter your phone number with country code:\n"
        "Example: +1234567890\n\n"
        "⚠️ Your session will be encrypted and stored securely"
    )
    
    back_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 Back to Dashboard", callback_data="nav|dashboard")
    ]])
    
    await query.message.reply_text(text, reply_markup=back_kb)

async def phone_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process phone number input during account addition"""
    user_id = update.effective_user.id
    state: Optional[UserState] = context.bot_data.get('user_states', {}).get(user_id)
    
    # Only process if in phone input state
    if not state or state.step != "phone":
        return
    
    raw_phone = update.message.text.strip()
    
    # Validate phone number format
    cleaned_phone = "+" + re.sub(r"\D", "", raw_phone)
    if not CONFIG.validate_phone(cleaned_phone):
        await update.message.reply_text(
            "❌ Invalid phone number!\n\n"
            "Please enter a valid number with country code:\n"
            "Example: +1234567890",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back to Dashboard", callback_data="nav|dashboard")
            ]])
        )
        return
    
    # Check if account already exists
    existing = await db.accounts.find_one({
        "user_id": user_id,
        "phone": cleaned_phone
    })
    if existing and existing.get("active"):
        await update.message.reply_text(
            f"⚠️ Account {cleaned_phone} already hosted!\n\n"
            "You can't host the same account twice.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back to Dashboard", callback_data="nav|dashboard")
            ]])
        )
        state.reset()
        return
    
    # Initialize Telethon client
    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        
        # Request OTP
        try:
            sent = await client.send_code_request(cleaned_phone)
            
            # Update state
            state.client = client
            state.phone = cleaned_phone
            state.phone_code_hash = sent.phone_code_hash
            state.step = "code"
            state.buffer = ""
            state.last_interaction = datetime.now().timestamp()
            
            # Show OTP keypad
            await update.message.reply_text(
                f"📱 OTP sent to {cleaned_phone}!\n\n"
                f"Enter the 5-digit code using the keypad below:",
                reply_markup=get_otp_keyboard(user_id, state)
            )
            
        except (PhoneNumberInvalidError, PhoneNumberBannedError) as e:
            await client.disconnect()
            await update.message.reply_text(
                "❌ Invalid or banned phone number!\n\n"
                "Please verify your number and try again.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back to Dashboard", callback_data="nav|dashboard")
                ]])
            )
            state.reset()
            
        except PhoneNumberFloodError as e:
            await client.disconnect()
            await update.message.reply_text(
                "⏳ Too many requests for this number!\n\n"
                "Please wait 24 hours before trying again.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back to Dashboard", callback_data="nav|dashboard")
                ]])
            )
            state.reset()
            
        except FloodWaitError as e:
            await client.disconnect()
            await update.message.reply_text(
                f"⏳ Telegram rate limit reached!\n\n"
                f"Please wait {e.seconds} seconds before trying again.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back to Dashboard", callback_data="nav|dashboard")
                ]])
            )
            state.reset()
            
    except Exception as e:
        logger.exception(f"Phone request error for {cleaned_phone}: {e}")
        if 'client' in locals() and client:
            await client.disconnect()
        await update.message.reply_text(
            "❌ Unexpected error during OTP request.\n\n"
            "Please try again later or contact support.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back to Dashboard", callback_data="nav|dashboard")
            ]])
        )
        state.reset()

async def show_account_list(update: Update, context: ContextTypes.DEFAULT_TYPE, parts):
    """Display paginated list of user's accounts"""
    query = update.callback_query
    user_id = query.from_user.id
    page = int(parts[2]) if len(parts) > 2 else 0
    
    accounts = await db.accounts.find({"user_id": user_id}).to_list(None)
    
    if not accounts:
        await query.answer("📭 No accounts added yet!", show_alert=True)
        await show_dashboard(update, context)
        return
    
    text = f"📱 MY ACCOUNTS ({len(accounts)})\n\nSelect an account to manage:"
    
    await safe_edit_or_send(
        query,
        text,
        reply_markup=get_accounts_keyboard(accounts, page)
    )

async def show_account_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, parts):
    """Show detailed view of a specific account"""
    query = update.callback_query
    user_id = query.from_user.id
    acc_id = parts[2]
    
    account = await db.accounts.find_one({
        "_id": acc_id,
        "user_id": user_id
    })
    
    if not account:
        await query.answer("Account not found!", show_alert=True)
        await show_account_list(update, context, ["acc", "list", "0"])
        return
    
    status = "🟢 Active" if account.get("active") else "🔴 Inactive"
    phone = account["phone"]
    
    text = (
        f"📱 ACCOUNT DETAILS\n\n"
        f"📞 Phone: {phone}\n"
        f"⚡ Status: {status}\n"
        f"📅 Added: {account.get('created_at', 'Unknown').strftime('%Y-%m-%d')}"
    )
    
    await safe_edit_or_send(
        query,
        text,
        reply_markup=get_account_detail_keyboard(acc_id, phone)
    )

async def show_delete_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE, parts):
    """Show confirmation dialog before account deletion"""
    query = update.callback_query
    user_id = query.from_user.id
    acc_id = parts[2]
    
    account = await db.accounts.find_one({
        "_id": acc_id,
        "user_id": user_id
    })
    
    if not account:
        await query.answer("Account not found!", show_alert=True)
        return
    
    phone = account["phone"]
    text = (
        f"⚠️ DELETE ACCOUNT CONFIRMATION\n\n"
        f"Are you sure you want to delete:\n"
        f"📱 {phone}\n\n"
        f"❗ This will permanently remove the account from your campaign!"
    )
    
    await safe_edit_or_send(
        query,
        text,
        reply_markup=get_delete_confirmation_keyboard(acc_id)
    )

async def account_deletion_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle actual account deletion after confirmation"""
    query = update.callback_query
    await query.answer()
    
    acc_id = query.data.split("|")[2]
    user_id = query.from_user.id
    
    # Delete account from database
    result = await db.accounts.delete_one({
        "_id": acc_id,
        "user_id": user_id
    })
    
    if result.deleted_count:
        # Also clean up any active sessions
        if 'user_states' in context.bot_data:
            for uid, state in list(context.bot_data['user_states'].items()):
                if hasattr(state, 'client') and state.client:
                    try:
                        await state.client.disconnect()
                    except:
                        pass
                    state.reset()
        
        await query.answer("✅ Account deleted successfully!", show_alert=True)
    else:
        await query.answer("❌ Account not found or already deleted!", show_alert=True)
    
    # Return to dashboard
    await show_dashboard(update, context)

async def show_delete_overview(update: Update, context: ContextTypes.DEFAULT_TYPE, parts):
    """Show overview for bulk account deletion"""
    query = update.callback_query
    user_id = query.from_user.id
    
    count = await db.accounts.count_documents({"user_id": user_id})
    
    if count == 0:
        await query.answer("📭 No accounts to delete!", show_alert=True)
        await show_dashboard(update, context)
        return
    
    text = (
        "🗑️ DELETE ACCOUNTS\n\n"
        f"You have {count} account(s) hosted.\n\n"
        "Select accounts to remove from your campaign:"
    )
    
    await safe_edit_or_send(
        query,
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 View & Delete Accounts", callback_data="acc|list|0")],
            [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="nav|dashboard")]
        ])
    )