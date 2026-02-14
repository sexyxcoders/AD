#!/usr/bin/env python3
"""Adimyze Bot - Production Telegram Marketing Automation Bot"""
import asyncio
import logging
import sys
import signal
from datetime import datetime, timezone
from typing import Optional

from telegram.ext import (
    ApplicationBuilder,
    PicklePersistence,
    ContextTypes,
    Application
)
from telegram import Update

from core import (
    get_bot_config,
    init_db,
    CONFIG
)
from handlers import register_handlers
from services import BROADCAST_MANAGER, initialize_broadcasting

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-15s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f"bot_{datetime.now().strftime('%Y%m%d')}.log")
    ]
)
logger = logging.getLogger(__name__)

# Global application reference for signal handling
_application: Optional[Application] = None

async def post_init(application: Application) -> None:
    """Initialize services after bot startup"""
    logger.info("=" * 60)
    logger.info("🚀 ADIMYZE BOT STARTING")
    logger.info("=" * 60)
    
    # Load configuration
    bot_token, api_id, api_hash, mongo_uri = get_bot_config()
    logger.info(f"✓ Configuration loaded (API ID: {api_id})")
    
    # Initialize database
    await init_db(mongo_uri)
    logger.info("✓ Database connection established")
    
    # Initialize broadcasting service
    await initialize_broadcasting()
    logger.info("✓ Broadcasting service initialized")
    
    # Initialize bot_data structure
    if 'user_states' not in application.bot_
        application.bot_data['user_states'] = {}
        logger.info("✓ User state storage initialized")
    
    # Set bot commands
    await application.bot.set_my_commands([
        ("start", "🚀 Start the bot / Show dashboard"),
        ("help", "ℹ️ How to use the bot"),
        ("accounts", "📱 Manage hosted accounts"),
        ("analytics", "📊 View campaign statistics"),
        ("stop", "⏹️ Stop active campaigns")
    ])
    logger.info("✓ Bot commands registered")
    
    logger.info("=" * 60)
    logger.info("✅ BOT STARTED SUCCESSFULLY")
    logger.info(f"   📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    logger.info(f"   👥 Handlers registered: {len(application.handlers)}")
    logger.info(f"   💾 Persistence: PicklePersistence (user_states.dat)")
    logger.info(f"   ⚙️  Default delay: {CONFIG.DEFAULT_DELAY}s")
    logger.info("=" * 60)

async def post_shutdown(application: Application) -> None:
    """Cleanup resources on shutdown"""
    logger.info("🛑 Shutting down services...")
    
    # Stop all active campaigns gracefully
    for user_id in list(BROADCAST_MANAGER._campaigns.keys()):
        await BROADCAST_MANAGER.stop_campaign(user_id)
    logger.info("✓ All campaigns stopped gracefully")
    
    # Cleanup Telethon sessions
    from services.telegram_client import SESSION_POOL
    for session_str, client in list(SESSION_POOL.items()):
        try:
            if client.is_connected():
                await client.disconnect()
        except:
            pass
    SESSION_POOL.clear()
    logger.info("✓ Telethon sessions cleaned up")
    
    # Close database connection
    from core.database import get_db_client
    try:
        get_db_client().close()
        logger.info("✓ Database connection closed")
    except Exception as e:
        logger.warning(f"Database shutdown warning: {e}")
    
    logger.info("=" * 60)
    logger.info("🛑 BOT SHUTDOWN COMPLETE")
    logger.info("=" * 60)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler with user notification"""
    logger.error(f"Exception while handling update {update}", exc_info=context.error)
    
    # Notify user if possible
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=(
                    "❌ An unexpected error occurred!\n\n"
                    "Our engineers have been notified. Please try again in a few minutes.\n\n"
                    "Need help? Contact @NexaCoders"
                )
            )
        except Exception as send_error:
            logger.debug(f"Failed to send error message to user: {send_error}")

def signal_handler(sig, frame):
    """Handle OS signals for graceful shutdown"""
    logger.info(f"\n\n⚠️ Received signal {sig}. Initiating graceful shutdown...")
    if _application:
        asyncio.create_task(_application.stop())
    sys.exit(0)

def main() -> None:
    """Main entry point with proper signal handling"""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("🔧 Starting Adimyze Bot initialization...")
    
    # Load configuration early for logging
    try:
        bot_token, _, _, _ = get_bot_config()
    except Exception as e:
        logger.critical(f"Configuration load failed: {e}")
        sys.exit(1)
    
    # Setup persistence
    persistence = PicklePersistence(
        filepath="user_states.dat",
        store_user_data=True,
        store_chat_data=False,
        store_bot_data=True,
        on_flush=True
    )
    
    # Build application
    global _application
    _application = (
        ApplicationBuilder()
        .token(bot_token)
        .persistence(persistence)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .get_updates_read_timeout(45)
        .build()
    )
    
    # Register handlers
    register_handlers(_application)
    
    # Add error handler
    _application.add_error_handler(error_handler)
    
    # Start the bot
    logger.info("📡 Starting bot polling...")
    _application.run_polling(
        close_loop=False,
        stop_signals=None,  # We handle signals manually
        allowed_updates=Update.ALL_TYPES
    )

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n🛑 Bot stopped by user (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Bot startup failed: {e}", exc_info=True)
        sys.exit(1)