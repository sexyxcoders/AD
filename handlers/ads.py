import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core import CONFIG, db
from keyboards.common_kb import get_back_button
from utils.safe_edit import safe_edit_or_send

logger = logging.getLogger(__name__)

async def ad_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle ad-related callbacks (set/view)"""
    query = update.callback_query
    await query.answer()
    
    action = query.data.split("|")[1]
    
    if action == "set":
        await show_ad_input(update, context)
    else:
        await query.answer("Unknown ad action", show_alert=True)

async def show_ad_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt user to enter ad message"""
    user_id = update.effective_user.id
    
    # Get current ad if exists
    ad_doc = await db.ads.find_one({"user_id": str(user_id)})
    current_ad = ad_doc.get("text", "") if ad_doc else ""
    
    # Build prompt text
    if current_ad:
        preview = current_ad[:100] + "..." if len(current_ad) > 100 else current_ad
        current_text = f"\n📝 Current Ad Preview:\n{preview}\n"
    else:
        current_text = "\n📝 No ad message set yet\n"
    
    text = (
        "💬 SET YOUR AD MESSAGE\n\n"
        "✨ Tips for effective ads:\n"
        "• Keep it concise (under 4000 chars)\n"
        "• Use relevant emojis sparingly\n"
        "• Include clear call-to-action\n"
        "• Avoid spam triggers (ALL CAPS, excessive links)\n\n"
        f"⚠️ Max length: {CONFIG.MAX_AD_LENGTH} characters\n"
        f"{current_text}\n"
        "Please send your new ad message now:"
    )
    
    # Set user state for ad input
    context.bot_data.setdefault('user_states', {})
    context.bot_data['user_states'][user_id] = UserState(step="set_ad")
    
    await query.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup([[get_back_button("dashboard")]])
    )

async def ad_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process ad message input"""
    user_id = update.effective_user.id
    state = context.bot_data.get('user_states', {}).get(user_id)
    
    # Only process if in ad setting state
    if not state or state.step != "set_ad":
        return
    
    ad_text = update.message.text.strip()
    
    # Validate length
    if not ad_text:
        await update.message.reply_text(
            "❌ Ad message cannot be empty!\n\nPlease send your ad message:",
            reply_markup=InlineKeyboardMarkup([[get_back_button("dashboard")]])
        )
        return
    
    if len(ad_text) > CONFIG.MAX_AD_LENGTH:
        await update.message.reply_text(
            f"❌ Message too long! ({len(ad_text)}/{CONFIG.MAX_AD_LENGTH} chars)\n\n"
            "Please send a shorter ad message:",
            reply_markup=InlineKeyboardMarkup([[get_back_button("dashboard")]])
        )
        return
    
    # Save to database
    try:
        await db.ads.update_one(
            {"user_id": str(user_id)},
            {
                "$set": {
                    "text": ad_text,
                    "updated_at": datetime.now(timezone.utc)
                }
            },
            upsert=True
        )
        
        # Reset state
        state.step = "idle"
        
        # Success message with preview
        preview = ad_text[:150] + "..." if len(ad_text) > 150 else ad_text
        await update.message.reply_text(
            "✅ Ad Message Saved Successfully!\n\n"
            f"📝 Preview:\n{preview}\n\n"
            "Your ad will be broadcasted according to your schedule.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Dashboard", callback_data="nav|dashboard"),
                InlineKeyboardButton("📊 Analytics", callback_data="stat|main")
            ]])
        )
        
    except Exception as e:
        logger.exception(f"Failed to save ad for user {user_id}: {e}")
        await update.message.reply_text(
            "❌ Failed to save ad message. Please try again.",
            reply_markup=InlineKeyboardMarkup([[get_back_button("dashboard")]])
        )