import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import IndexModel, ASCENDING, TEXT

logger = logging.getLogger(__name__)

# Global database client and reference
_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None

async def init_db(mongo_uri: str, db_name: str = "adimyze_db") -> AsyncIOMotorDatabase:
    """
    Initialize MongoDB connection with proper indexing
    
    Args:
        mongo_uri: MongoDB connection string
        db_name: Database name to use
    
    Returns:
        Initialized database instance
    """
    global _client, _db
    
    if _db is not None:
        return _db
    
    try:
        # Initialize connection pool
        _client = AsyncIOMotorClient(
            mongo_uri,
            maxPoolSize=50,
            minPoolSize=5,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=10000,
            retryWrites=True,
            retryReads=True
        )
        
        # Test connection
        await _client.admin.command('ping')
        logger.info("✓ MongoDB connection established")
        
        _db = _client[db_name]
        
        # Create essential indexes
        await _setup_indexes(_db)
        
        return _db
        
    except Exception as e:
        logger.exception(f"✗ Failed to initialize MongoDB: {e}")
        raise

async def _setup_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create optimized indexes for all collections"""
    # Accounts collection indexes
    await db.accounts.create_indexes([
        IndexModel([("user_id", ASCENDING)], name="user_accounts"),
        IndexModel([("phone", ASCENDING)], name="phone_unique", unique=True),
        IndexModel([("active", ASCENDING)], name="active_status"),
        IndexModel([("created_at", ASCENDING)], name="creation_time")
    ])
    
    # Ads collection indexes
    await db.ads.create_indexes([
        IndexModel([("user_id", ASCENDING)], name="user_ads", unique=True),
        IndexModel([("updated_at", ASCENDING)], name="update_time")
    ])
    
    # Users collection indexes
    await db.users.create_indexes([
        IndexModel([("user_id", ASCENDING)], name="telegram_user", unique=True),
        IndexModel([("delay", ASCENDING)], name="broadcast_delay")
    ])
    
    # Analytics collection indexes (for future use)
    await db.analytics.create_indexes([
        IndexModel([("user_id", ASCENDING), ("timestamp", ASCENDING)], name="user_analytics"),
        IndexModel([("account_id", ASCENDING)], name="account_metrics"),
        IndexModel([("success", ASCENDING)], name="success_rate")
    ])
    
    logger.info("✓ Database indexes created successfully")

def get_db_client() -> AsyncIOMotorClient:
    """Get the raw MongoDB client instance"""
    if _client is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _client

# Collection accessors with type hints
class DatabaseCollections:
    """Typed access to database collections"""
    
    def __init__(self, db: AsyncIOMotorDatabase):
        self.accounts = db.accounts
        self.ads = db.ads
        self.users = db.users
        self.analytics = db.analytics
    
    async def get_user_accounts(self, user_id: int, active_only: bool = False) -> list:
        """Get all accounts for a user with optional active filter"""
        query = {"user_id": user_id}
        if active_only:
            query["active"] = True
        return await self.accounts.find(query).to_list(None)
    
    async def get_user_ad(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get current ad message for user"""
        return await self.ads.find_one({"user_id": str(user_id)})
    
    async def get_user_settings(self, user_id: int) -> Dict[str, Any]:
        """Get user settings with defaults"""
        doc = await self.users.find_one({"user_id": str(user_id)})
        return doc or {"user_id": str(user_id), "delay": CONFIG.DEFAULT_DELAY}

# Global database instance accessor
def get_db() -> DatabaseCollections:
    """Get typed database collections accessor"""
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return DatabaseCollections(_db)

# ❌ REMOVE THIS
# db = get_db()

# Instead export function only
__all__ = ["init_db", "get_db", "get_db_client", "DatabaseCollections"]