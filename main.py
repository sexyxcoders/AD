#!/usr/bin/env python3
"""Adimyze Bot - Production Telegram Marketing Automation Bot"""

import asyncio
import logging
import sys
import signal
from datetime import datetime
from typing import Optional

from telegram.ext import (
    ApplicationBuilder,
    PicklePersistence,
    ContextTypes,
    Application,
)
from telegram import Update

from core import get_bot_config, init_db, CONFIG
from handlers import register_handlers
from services import BROADCAST_MANAGER, initialize_broadcasting

# ================= LOGGING ================= #

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-15s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f"bot_{datetime.now().strftime('%Y%m%d')}.log"),
    ],
)
logger = logging.getLogger(__name__)

# Global application reference for signal handling
_application: Optional[Application] = None

# ================= POST INIT ================= #

async def post_init(application: Application) -> None:
    """Initialize services after bot startup"""

    logger.info("=" * 60)
    logger.info("🚀 ADIMYZE BOT STARTING")
    logger.info("=" * 60)

    # Load configuration
    bot_token, api_id, api_hash, mongo_uri = get_bot_config()
    logger.info(f"✓ Config loaded (API ID: {api_id})")

    # Initialize database
    await init_db(mongo_uri)
    logger.info("✓ Database connected")

    # Initialize broadcasting
    await initialize_broadcasting()
    logger.info("✓ Broadcasting initialized")

    # Initialize bot_data
    application.bot_data.setdefault("user_states", {})
    logger.info("✓ User state storage initialized")

    # Set bot commands
    await application.bot.set_my_commands([
        ("start", "Start bot"),
        ("help", "Help info"),
        ("accounts", "Manage accounts"),
        ("analytics", "View analytics"),
        ("stop", "Stop campaigns"),
    ])
    logger.info("✓ Bot commands registered")

    logger.info("=" * 60)
    logger.info("✅ BOT STARTED SUCCESSFULLY")
    logger.info(f"📅 {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    logger.info(f"👥 Handlers: {len(application.handlers)}")
    logger.info(f"💾 Persistence: user_states.dat")
    logger.info(f"⚙ Default delay: {CONFIG.DEFAULT_DELAY}s")
    logger.info("=" * 60)

# ================= SHUTDOWN ================= #

async def post_shutdown(application: Application) -> None:
    """Cleanup on shutdown"""

    logger.info("🛑 Shutting down...")

    # Stop campaigns
    for user_id in list(BROADCAST_MANAGER._campaigns.keys()):
        await BROADCAST_MANAGER.stop_campaign(user_id)
    logger.info("✓ Campaigns stopped")

    # Disconnect Telethon sessions
    from services.telegram_client import SESSION_POOL
    for client in SESSION_POOL.values():
        try:
            if client.is_connected():
                await client.disconnect()
        except:
            pass
    SESSION_POOL.clear()
    logger.info("✓ Telethon cleaned")

    # Close DB
    from core.database import get_db_client
    try:
        get_db_client().close()
        logger.info("✓ Database closed")
    except Exception as e:
        logger.warning(f"DB close error: {e}")

    logger.info("🛑 BOT SHUTDOWN COMPLETE")

# ================= ERROR HANDLER ================= #

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Update error", exc_info=context.error)

    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Error occurred. Try again later."
            )
        except:
            pass

# ================= SIGNAL HANDLER ================= #

def signal_handler(sig, frame):
    logger.info(f"⚠️ Signal {sig} received. Shutting down...")
    if _application:
        asyncio.create_task(_application.stop())
    sys.exit(0)

# ================= MAIN ================= #

def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("🔧 Initializing bot...")

    # Load token
    try:
        bot_token, _, _, _ = get_bot_config()
    except Exception as e:
        logger.critical(f"Config error: {e}")
        sys.exit(1)

    # Persistence
    persistence = PicklePersistence(
        filepath="user_states.dat",
        store_user_data=True,
        store_chat_data=False,
        store_bot_data=True,
    )

    # Build app
    global _application
    _application = (
        ApplicationBuilder()
        .token(bot_token)
        .persistence(persistence)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Handlers
    register_handlers(_application)

    # Error handler
    _application.add_error_handler(error_handler)

    # Start polling
    logger.info("📡 Bot polling started...")
    _application.run_polling(allowed_updates=Update.ALL_TYPES)

# ================= RUN ================= #

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by Ctrl+C")
    except Exception as e:
        logger.critical(f"Startup failed: {e}", exc_info=True)