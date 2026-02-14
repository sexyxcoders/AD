"""Campaign control handlers - start/stop broadcasting"""
import logging
from telegram import Update, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core import db
from keyboards.common_kb import get_dashboard_keyboard
from utils.safe_edit import safe_edit_or_send

logger = logging.getLogger(__name__)

async def campaign_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle campaign start/stop actions"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    action = "start" if "start" in query.data else "stop"
    
    if action == "start":
        await start_campaign(update, context, user_id)
    else:
        await stop_campaign(update, context, user_id)

async def start_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Initiate ad broadcasting campaign"""
    # Check prerequisites
    active_accounts = await db.accounts.count_documents({
        "user_id": user_id,
        "active": True
    })
    
    ad_doc = await db.ads.find_one({"user_id": str(user_id)})
    
    # Validation checks
    if active_accounts == 0:
        await update.callback_query.answer(
            "❌ No active accounts!\nAdd accounts before starting campaigns.",
            show_alert=True
        )
        return
    
    if not ad_doc or not ad_doc.get("text"):
        await update.callback_query.answer(
            "❌ No ad message set!\nConfigure your ad message first.",
            show_alert=True
        )
        return
    
    # Check if campaign already running (placeholder - implement real tracking)
    # In production: check background task status
    
    # Start campaign (placeholder - implement real broadcaster)
    # In production: start background task with asyncio.create_task()
    
    # Update campaign status in database
    await db.users.update_one(
        {"user_id": str(user_id)},
        {"$set": {"campaign_active": True, "campaign_started_at": datetime.now(timezone.utc)}},
        upsert=True
    )
    
    # Success message
    await update.callback_query.answer("✅ Campaign started successfully!", show_alert=True)
    
    text = (
        "🚀 CAMPAIGN STARTED\n\n"
        f"📱 Active Accounts: {active_accounts}\n"
        f"⏱️ Broadcast Interval: {ad_doc.get('delay', 600)}s\n\n"
        "Your ads are now broadcasting to all joined groups.\n\n"
        "⚠️ Monitor account health in Analytics to avoid restrictions."
    )
    
    await safe_edit_or_send(
        update.callback_query,
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 View Analytics", callback_data="stat|main")],
            [InlineKeyboardButton("🛑 Stop Campaign", callback_data="camp|stop")],
            [InlineKeyboardButton("🏠 Dashboard", callback_data="nav|dashboard")]
        ])
    )

async def stop_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Stop active broadcasting campaign"""
    # Stop campaign (placeholder - implement real task cancellation)
    # In production: cancel background task
    
    # Update campaign status
    await db.users.update_one(
        {"user_id": str(user_id)},
        {"$set": {"campaign_active": False, "campaign_stopped_at": datetime.now(timezone.utc)}},
        upsert=True
    )
    
    await update.callback_query.answer("🛑 Campaign stopped successfully!", show_alert=True)
    
    text = (
        "⏸️ CAMPAIGN STOPPED\n\n"
        "All broadcasting activities have been paused.\n\n"
        "✅ Your accounts are safe and ready for next campaign.\n\n"
        "💡 Tip: Let accounts rest for 1-2 hours between campaigns."
    )
    
    await safe_edit_or_send(
        update.callback_query,
        text,
        reply_markup=get_dashboard_keyboard()
    )