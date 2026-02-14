import configparser
import os
import logging
from typing import Tuple, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Configuration sources priority: ENV > config.ini > defaults
class BotConfigLoader:
    """Secure configuration loader with validation"""
    
    def __init__(self, config_path: str = "config.ini"):
        self.config_path = config_path
        self.parser = configparser.ConfigParser()
        self._load_config_file()
    
    def _load_config_file(self) -> None:
        """Load configuration from INI file if exists"""
        if Path(self.config_path).exists():
            try:
                self.parser.read(self.config_path)
                logger.info(f"✓ Loaded configuration from {self.config_path}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to read config file: {e}")
        else:
            logger.warning(f"⚠️ Config file not found at {self.config_path}")
    
    def _get_value(self, section: str, key: str, env_var: str, required: bool = True) -> str:
        """Get configuration value with ENV fallback"""
        # Try environment variable first
        env_value = os.getenv(env_var)
        if env_value:
            return env_value
        
        # Try config file
        if self.parser.has_section(section) and self.parser.has_option(section, key):
            return self.parser[section][key]
        
        # Handle missing required value
        if required:
            raise ValueError(
                f"Missing required configuration: {key} "
                f"(section: {section}, env var: {env_var})"
            )
        return ""
    
    def load_telegram_config(self) -> Tuple[str, int, str]:
        """Load Telegram API credentials with validation"""
        bot_token = self._get_value("telegram", "bot_token", "BOT_TOKEN")
        api_id_raw = self._get_value("telegram", "api_id", "API_ID")
        api_hash = self._get_value("telegram", "api_hash", "API_HASH")
        
        try:
            api_id = int(api_id_raw)
        except ValueError:
            raise ValueError(f"Invalid API_ID value: {api_id_raw}")
        
        if not bot_token or len(bot_token) < 10:
            raise ValueError("Invalid BOT_TOKEN format")
        if not api_hash or len(api_hash) < 32:
            raise ValueError("Invalid API_HASH format")
        
        return bot_token, api_id, api_hash
    
    def load_mongo_config(self) -> str:
        """Load MongoDB URI with validation"""
        mongo_uri = self._get_value("mongo", "uri", "MONGO_URI")
        
        if not mongo_uri.startswith(("mongodb://", "mongodb+srv://")):
            raise ValueError("Invalid MONGO_URI format - must start with mongodb:// or mongodb+srv://")
        
        return mongo_uri

# Global configuration cache
_BOT_TOKEN: Optional[str] = None
_API_ID: Optional[int] = None
_API_HASH: Optional[str] = None
_MONGO_URI: Optional[str] = None

def get_bot_config() -> Tuple[str, int, str, str]:
    """
    Get validated bot configuration
    
    Returns:
        Tuple of (BOT_TOKEN, API_ID, API_HASH, MONGO_URI)
    """
    global _BOT_TOKEN, _API_ID, _API_HASH, _MONGO_URI
    
    if all([_BOT_TOKEN, _API_ID, _API_HASH, _MONGO_URI]):
        return _BOT_TOKEN, _API_ID, _API_HASH, _MONGO_URI
    
    loader = BotConfigLoader()
    
    try:
        _BOT_TOKEN, _API_ID, _API_HASH = loader.load_telegram_config()
        _MONGO_URI = loader.load_mongo_config()
        
        # Mask sensitive values for logging
        masked_token = f"{_BOT_TOKEN[:5]}...{_BOT_TOKEN[-5:]}" if _BOT_TOKEN else "N/A"
        masked_hash = f"{_API_HASH[:8]}...{_API_HASH[-8:]}" if _API_HASH else "N/A"
        
        logger.info(
            "✓ Bot configuration loaded:\n"
            f"  • Bot Token: {masked_token}\n"
            f"  • API ID: {_API_ID}\n"
            f"  • API Hash: {masked_hash}\n"
            f"  • MongoDB URI: {'***' if _MONGO_URI else 'N/A'}"
        )
        
        return _BOT_TOKEN, _API_ID, _API_HASH, _MONGO_URI
        
    except Exception as e:
        logger.exception(f"✗ Configuration loading failed: {e}")
        raise

# Convenience exports (lazy-loaded on first access)
@property
def BOT_TOKEN() -> str:
    return get_bot_config()[0]

@property
def API_ID() -> int:
    return get_bot_config()[1]

@property
def API_HASH() -> str:
    return get_bot_config()[2]

@property
def MONGO_URI() -> str:
    return get_bot_config()[3]

# Type hints for IDE support
BOT_TOKEN: str
API_ID: int
API_HASH: str
MONGO_URI: str