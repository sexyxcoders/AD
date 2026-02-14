import re
from dataclasses import dataclass, field
from typing import ClassVar, Pattern

@dataclass(frozen=True)
class BotConfig:
    """Immutable configuration constants with validation"""
    
    # Media assets
    BANNER_URL: str = "https://files.catbox.moe/zttfbe.jpg"
    
    # Profile customization
    PROFILE_NAME: str = "Adimyze Pro"
    PROFILE_BIO: str = "🚀 Professional Telegram Marketing Automation | Managed by @nexaxoders"
    
    # Security constraints
    MIN_PHONE_LENGTH: int = 8
    MAX_PHONE_LENGTH: int = 15
    OTP_LENGTH: int = 5
    MAX_AD_LENGTH: int = 4000
    
    # Broadcasting constraints
    MIN_DELAY: int = 300      # 5 minutes (aggressive)
    DEFAULT_DELAY: int = 600  # 10 minutes (balanced)
    MAX_DELAY: int = 86400    # 24 hours (conservative)
    
    # Session management
    SESSION_TIMEOUT: int = 300  # 5 minutes
    
    # Validation patterns
    PHONE_PATTERN: ClassVar[Pattern] = re.compile(r'^\+?[1-9]\d{7,14}$')
    URL_PATTERN: ClassVar[Pattern] = re.compile(
        r'^https?://(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?:/[^\s]*)?$'
    )
    
    def validate_phone(self, phone: str) -> bool:
        """Validate phone number format"""
        cleaned = re.sub(r'\D', '', phone)
        return (self.MIN_PHONE_LENGTH <= len(cleaned) <= self.MAX_PHONE_LENGTH 
                and bool(self.PHONE_PATTERN.match(f"+{cleaned}")))
    
    def validate_delay(self, delay: int) -> int:
        """Clamp delay value to allowed range"""
        return max(self.MIN_DELAY, min(delay, self.MAX_DELAY))
    
    def validate_ad_length(self, text: str) -> bool:
        """Check if ad message is within length limits"""
        return len(text) <= self.MAX_AD_LENGTH

# Singleton instance - immutable configuration
CONFIG: BotConfig = BotConfig()