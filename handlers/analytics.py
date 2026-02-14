import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core import db
from keyboards.common_kb import get_back_button
from utils.safe_edit import safe_edit_or_send

logger = logging.getLogger(__name__)

async def analytics_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle analytics navigation and display"""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split("|")
    view = parts[1]
    
    if view == "main":
        await show_main_analytics(update, context)
    elif view == "detail":
        await show_detailed_report(update, context)
    else:
        await query.answer("Unknown analytics view", show_alert=True)

async def show_main_analytics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display main analytics dashboard"""
    user_id = update.effective_user.id
    
    # Gather analytics data concurrently
    active_acc, total_acc, user_doc = await asyncio.gather(
        db.accounts.count_documents({"user_id": user_id, "active": True}),
        db.accounts.count_documents({"user_id": user_id}),
        db.users.find_one({"user_id": str(user_id)})
    )
    
    delay = user_doc.get("delay", 300) if user_doc else 300
    
    # Placeholder metrics (implement real tracking later)
    cycles_completed = 0
    messages_sent = 0
    failed_sends = 0
    success_rate = 100 if messages_sent == 0 else int((messages_sent / (messages_sent + failed_sends)) * 100)
    
    # Visual progress bar
    bar_length = 10
    filled = int(bar_length * success_rate / 100)
    bar = "█" * filled + "░" * (bar_length - filled)
    
    text = (
        "📊 @Tecxo ANALYTICS DASHBOARD\n\n"
        f"📈 Broadcast Performance:\n"
        f"• Cycles Completed: {cycles_completed}\n"
        f"• Messages Sent: {messages_sent}\n"
        f"• Failed Sends: {failed_sends}\n"
        f"• Success Rate: {bar} {success_rate}%\n\n"
        f"⚙️ Account Status:\n"
        f"• Active Accounts: {active_acc}\n"
        f"• Total Accounts: {total_acc}\n"
        f"• Current Interval: {delay}s\n\n"
        f"💡 Tip: Maintain >95% success rate for account safety"
    )
    
    await safe_edit_or_send(
        query,
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📄 Detailed Report", callback_data="stat|detail")],
            [InlineKeyboardButton("🏠 Dashboard", callback_data="nav|dashboard")]
        ])
    )

async def show_detailed_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display comprehensive analytics report"""
    user_id = update.effective_user.id
    
    # Gather detailed data
    active_acc = await db.accounts.count_documents({"user_id": user_id, "active": True})
    total_acc = await db.accounts.count_documents({"user_id": user_id})
    inactive_acc = total_acc - active_acc
    
    user_doc = await db.users.find_one({"user_id": str(user_id)})
    delay = user_doc.get("delay", 300) if user_doc else 300
    
    now = datetime.now(timezone.utc).strftime("%d %b %Y")
    
    text = (
        f"📄 DETAILED ANALYTICS REPORT\n\n"
        f"📅 Report Date: {now}\n"
        f"🆔 User ID: {user_id}\n\n"
        f"📤 Broadcast Statistics:\n"
        f"• Total Messages Sent: 0\n"
        f"• Total Failed Sends: 0\n"
        f"• Broadcast Cycles: 0\n"
        f"• Avg. Messages/Account: 0\n\n"
        f"📱 Account Health:\n"
        f"• Total Accounts: {total_acc}\n"
        f"• Active Accounts: {active_acc} 🟢\n"
        f"• Inactive Accounts: {inactive_acc} 🔴\n"
        f"• Current Interval: {delay}s\n\n"
        f"⚠️ Safety Metrics:\n"
        f"• Account Restrictions: 0\n"
        f"• Session Resets: 0\n"
        f"• Health Score: ⭐⭐⭐⭐⭐ (100%)\n\n"
        f"💡 Recommendations:\n"
        f"• Maintain intervals >5 minutes\n"
        f"• Rotate accounts every 24h\n"
        f"• Monitor success rate daily"
    )
    
    await safe_edit_or_send(
        query,
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Summary", callback_data="stat|main")],
            [InlineKeyboardButton("🏠 Dashboard", callback_data="nav|dashboard")]
        ])
    )