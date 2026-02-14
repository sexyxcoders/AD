import logging
import re
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core import CONFIG, db
from keyboards.delay_kb import get_delay_keyboard
from utils.safe_edit import safe_edit_or_send

logger = logging.getLogger(__name__)

async def delay_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle delay configuration callbacks"""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split("|")
    action = parts[0]
    
    if action == "delay":
        await show_delay_settings(update, context)
    elif action == "setdelay":
        await set_delay(update, context, int(parts[1]))
    else:
        await query.answer("Unknown delay action", show_alert=True)

async def show_delay_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display current delay settings and options"""
    user_id = update.effective_user.id
    
    # Get current delay
    user_doc = await db.users.find_one({"user_id": str(user_id)})
    current_delay = user_doc.get("delay", CONFIG.DEFAULT_DELAY) if user_doc else CONFIG.DEFAULT_DELAY
    
    # Build human-readable delay description
    if current_delay <= 300:
        risk_level = "🔴 High Risk"
        description = "Aggressive (may trigger Telegram restrictions)"
    elif current_delay <= 600:
        risk_level = "🟡 Medium Risk"
        description = "Balanced (recommended for most users)"
    else:
        risk_level = "🟢 Low Risk"
        description = "Conservative (safest option)"
    
    text = (
        "⏱️ BROADCAST CYCLE INTERVAL\n\n"
        f"Current Setting: {current_delay}s ({risk_level})\n"
        f"{description}\n\n"
        "Recommended Intervals:\n"
        "• 300s (5 min)  🔴 Aggressive\n"
        "• 600s (10 min) 🟡 Balanced (Recommended)\n"
        "• 1200s (20 min) 🟢 Conservative\n\n"
        "⚠️ WARNING: Intervals below 300s significantly increase risk of account restrictions!"
    )
    
    await safe_edit_or_send(
        query,
        text,
        reply_markup=get_delay_keyboard(current_delay)
    )

async def set_delay(update: Update, context: ContextTypes.DEFAULT_TYPE, delay: int):
    """Set broadcast delay to predefined value"""
    user_id = update.effective_user.id
    
    # Validate and clamp delay value
    safe_delay = CONFIG.validate_delay(delay)
    
    # Update database
    await db.users.update_one(
        {"user_id": str(user_id)},
        {"$set": {"delay": safe_delay}},
        upsert=True
    )
    
    # Show confirmation with updated settings
    await show_delay_settings(update, context)
    await update.callback_query.answer(
        f"✅ Interval set to {safe_delay} seconds",
        show_alert=True
    )

async def custom_delay_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle custom delay input via text message"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # Only process if user is in delay configuration flow
    # (We don't use state for this since it's a simple numeric input)
    # Instead, we check if the message looks like a delay value
    
    # Extract number from message
    match = re.search(r'\d+', text)
    if not match:
        # Not a delay setting message - ignore
        return
    
    try:
        delay = int(match.group())
        
        # Validate delay
        if delay < CONFIG.MIN_DELAY:
            await update.message.reply_text(
                f"❌ Minimum interval is {CONFIG.MIN_DELAY} seconds (5 minutes)!\n\n"
                "Lower intervals risk account restrictions.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back to Settings", callback_data="delay|nav")
                ]])
            )
            return
        
        if delay > CONFIG.MAX_DELAY:
            await update.message.reply_text(
                f"❌ Maximum interval is {CONFIG.MAX_DELAY} seconds (24 hours)!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back to Settings", callback_data="delay|nav")
                ]])
            )
            return
        
        # Save to database
        await db.users.update_one(
            {"user_id": str(user_id)},
            {"$set": {"delay": delay}},
            upsert=True
        )
        
        # Confirmation
        await update.message.reply_text(
            f"✅ Custom interval set to {delay} seconds\n\n"
            f"Your ads will broadcast every {delay//60} minutes.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Dashboard", callback_data="nav|dashboard"),
                InlineKeyboardButton("⏱️ Change Interval", callback_data="delay|nav")
            ]])
        )
        
    except ValueError:
        await update.message.reply_text(
            "❌ Please enter a valid number of seconds",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back to Settings", callback_data="delay|nav")
            ]])
        )