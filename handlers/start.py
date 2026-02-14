import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core import CONFIG, db
from keyboards.start_kb import get_start_keyboard
from keyboards.dashboard_kb import get_dashboard_keyboard
from utils.safe_edit import safe_edit_or_send

logger = logging.getLogger(__name__)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command - show welcome screen or dashboard"""
    user_id = update.effective_user.id
    
    # Initialize user document if new
    await db.users.update_one(
        {"user_id": str(user_id)},
        {"$setOnInsert": {
            "user_id": str(user_id),
            "created_at": datetime.now(timezone.utc),
            "delay": CONFIG.DEFAULT_DELAY
        }},
        upsert=True
    )
    
    # Show welcome screen for new users, dashboard for returning users
    is_new = not update.message or not update.message.text.startswith("/start ")
    if is_new:
        await show_welcome(update, context)
    else:
        await show_dashboard(update, context)

async def show_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display welcome screen with bot capabilities"""
    text = (
        "╰_╯ Welcome to @Tecxo Free Ads Bot — The Future of Telegram Automation\n\n"
        "✨ Premium Features:\n"
        "• Multi-Account Broadcasting\n"
        "• Smart Delay Management\n"
        "• Real-time Analytics\n"
        "• Profile Auto-Optimization\n\n"
        "⚠️ Note: Use responsibly to avoid Telegram restrictions\n\n"
        "Support: @NexaCoders"
    )
    
    if update.callback_query:
        await safe_edit_or_send(
            update.callback_query,
            text,
            reply_markup=get_start_keyboard(),
            photo_url=CONFIG.BANNER_URL
        )
    else:
        await update.message.reply_photo(
            photo=CONFIG.BANNER_URL,
            caption=text,
            reply_markup=get_start_keyboard()
        )

async def show_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display user dashboard with account status overview"""
    user_id = update.effective_user.id
    
    # Fetch dashboard data concurrently
    active_acc, total_acc, ad_doc, user_doc = await asyncio.gather(
        db.accounts.count_documents({"user_id": user_id, "active": True}),
        db.accounts.count_documents({"user_id": user_id}),
        db.ads.find_one({"user_id": str(user_id)}),
        db.users.find_one({"user_id": str(user_id)})
    )
    
    delay = user_doc.get("delay", CONFIG.DEFAULT_DELAY) if user_doc else CONFIG.DEFAULT_DELAY
    ad_status = "✅ Set" if ad_doc and ad_doc.get("text") else "❌ Not Set"
    campaign_status = "⏸️ Stopped"  # Placeholder - implement real status later
    
    text = (
        f"╰_╯ @NexaCoders Ads DASHBOARD\n\n"
        f"📱 Hosted Accounts: {active_acc}/{total_acc}\n"
        f"💬 Ad Message: {ad_status}\n"
        f"⏱️ Cycle Interval: {delay}s\n"
        f"🚀 Advertising Status: {campaign_status}\n\n"
        f"╰_╯ Choose an action below to continue"
    )
    
    if update.callback_query:
        await safe_edit_or_send(
            update.callback_query,
            text,
            reply_markup=get_dashboard_keyboard(),
            photo_url=CONFIG.BANNER_URL
        )
    else:
        await update.message.reply_photo(
            photo=CONFIG.BANNER_URL,
            caption=text,
            reply_markup=get_dashboard_keyboard()
        )

async def navigation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle navigation between bot sections"""
    query = update.callback_query
    await query.answer()
    
    destination = query.data.split("|")[1]
    
    navigation_map = {
        "start": show_welcome,
        "dashboard": show_dashboard,
        "howto": show_how_to
    }
    
    handler = navigation_map.get(destination)
    if handler:
        await handler(update, context)
    else:
        await query.answer("Unknown navigation destination", show_alert=True)

async def show_how_to(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display usage instructions"""
    text = (
        "╰_╯ HOW TO USE\n\n"
        "1️⃣ Add Account → Host your Telegram account\n"
        "2️⃣ Set Ad Message → Create your promotional text\n"
        "3️⃣ Set Time Interval → Configure broadcast frequency\n"
        "4️⃣ Start Ads → Begin automated broadcasting\n\n"
        "⚠️ Critical Safety Tips:\n"
        "• Never use intervals < 300s (5 min)\n"
        "• Rotate accounts regularly\n"
        "• Avoid spammy content\n"
        "• Monitor account health in Analytics\n\n"
        "Violating these guidelines may result in account restrictions!"
    )
    
    back_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 Back to Dashboard", callback_data="nav|dashboard")
    ]])
    
    await safe_edit_or_send(
        update.callback_query,
        text,
        reply_markup=back_kb
    )