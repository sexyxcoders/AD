"""Input validation utilities with security-focused checks"""
import re
import string
from typing import Tuple, Optional
from datetime import datetime

class ValidationError(Exception):
    """Custom exception for validation failures"""
    pass

def validate_phone_number(phone: str) -> Tuple[bool, str]:
    """
    Validate international phone number format.
    
    Requirements:
    - Must start with + followed by country code
    - 8-15 digits total (excluding +)
    - No spaces or special characters except +
    - Valid country code length (1-3 digits)
    
    Args:
        phone: Raw phone number input
    
    Returns:
        Tuple of (is_valid: bool, normalized_phone: str)
    
    Raises:
        ValidationError: With specific reason for failure
    """
    # Remove whitespace and common separators
    cleaned = re.sub(r'[\s\-\(\)]', '', phone.strip())
    
    # Ensure starts with +
    if not cleaned.startswith('+'):
        cleaned = '+' + cleaned
    
    # Basic format validation
    if not re.match(r'^\+\d{7,14}$', cleaned):
        raise ValidationError(
            "Invalid phone format. Must be international format starting with + "
            "(e.g., +1234567890). Length must be 8-15 digits after country code."
        )
    
    # Country code validation (1-3 digits after +)
    country_code_match = re.match(r'^\+(\d{1,3})', cleaned)
    if not country_code_match:
        raise ValidationError("Invalid country code. Must be 1-3 digits after +")
    
    country_code = country_code_match.group(1)
    
    # Known invalid country codes
    invalid_codes = {'0', '00', '000', '333', '555', '777', '999'}
    if country_code in invalid_codes:
        raise ValidationError(f"Invalid country code: +{country_code}")
    
    # Length validation (total digits 8-15 excluding +)
    digit_count = len(re.sub(r'\D', '', cleaned))
    if digit_count < 8 or digit_count > 15:
        raise ValidationError(
            f"Phone number length invalid. Must be 8-15 digits total (yours: {digit_count})"
        )
    
    return True, cleaned

def validate_ad_message(text: str, max_length: int = 4000) -> Tuple[bool, str]:
    """
    Validate ad message content for safety and policy compliance.
    
    Safety checks:
    - Length limits (Telegram max 4096 chars, we enforce 4000 for safety)
    - Spam trigger detection (excessive caps, links, emojis)
    - Prohibited content patterns (scams, phishing indicators)
    - Unicode safety (no zero-width chars, directional overrides)
    
    Args:
        text: Raw ad message text
        max_length: Maximum allowed length (default 4000)
    
    Returns:
        Tuple of (is_valid: bool, sanitized_text: str)
    
    Raises:
        ValidationError: With specific policy violation reason
    """
    if not text or not text.strip():
        raise ValidationError("Ad message cannot be empty")
    
    # Length validation
    if len(text) > max_length:
        raise ValidationError(
            f"Message too long ({len(text)}/{max_length} characters). "
            "Telegram limits messages to 4096 characters. Please shorten your message."
        )
    
    # Unicode safety checks
    if re.search(r'[\u200B-\u200F\u202A-\u202E]', text):
        raise ValidationError(
            "Message contains hidden formatting characters (zero-width spaces, "
            "directional overrides). These are often used in scams and are prohibited."
        )
    
    # Excessive capitalization (spam indicator)
    alpha_chars = re.sub(r'[^a-zA-Z]', '', text)
    if alpha_chars and sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars) > 0.7:
        if len(alpha_chars) > 20:  # Only flag long messages with excessive caps
            raise ValidationError(
                "Excessive capitalization detected. Messages with >70% uppercase letters "
                "are often flagged as spam by Telegram. Please use normal capitalization."
            )
    
    # Link limit (prevent spam)
    links = re.findall(r'https?://[^\s]+', text)
    if len(links) > 3:
        raise ValidationError(
            f"Too many links detected ({len(links)}). Messages with >3 links are "
            "often flagged as spam. Reduce links or use a link shortener."
        )
    
    # Emoji density check (spam indicator)
    emoji_count = len(re.findall(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF]', text))
    if emoji_count > 15:
        raise ValidationError(
            f"Excessive emojis detected ({emoji_count}). Messages with >15 emojis are "
            "often flagged as spam. Please reduce emoji usage."
        )
    
    # Prohibited content patterns (scam/phishing indicators)
    scam_patterns = [
        r'(?i)free.*gift.*card',
        r'(?i)click.*link.*win',
        r'(?i)send.*money.*double',
        r'(?i)urgent.*action.*required',
        r'(?i)verify.*account.*immediately',
        r'(?i)limited.*time.*offer',
        r'(?i)congratulations.*selected',
        r'(?i)claim.*prize.*now',
    ]
    
    for pattern in scam_patterns:
        if re.search(pattern, text):
            raise ValidationError(
                "Message contains patterns commonly associated with scams/phishing. "
                "Such content violates Telegram's Terms of Service and may get your "
                "account restricted. Please revise your message."
            )
    
    # Sanitize dangerous characters for Markdown
    sanitized = text.replace('\\', '\\\\').replace('[', '\\[').replace(']', '\\]')
    
    return True, sanitized

def validate_delay_interval(seconds: int) -> int:
    """
    Validate broadcast delay interval with safety enforcement.
    
    Safety thresholds:
    - Absolute minimum: 300s (5 minutes) - below this risks instant restrictions
    - Recommended minimum: 600s (10 minutes) for sustainable operation
    - Maximum: 86400s (24 hours) - practical upper bound
    
    Args:
        seconds: Proposed delay interval in seconds
    
    Returns:
        Clamped and validated delay value
    
    Raises:
        ValidationError: If value is completely unreasonable (<60 or >31536000)
    """
    try:
        delay = int(seconds)
    except (ValueError, TypeError):
        raise ValidationError("Delay must be a valid number")
    
    # Absolute sanity checks
    if delay < 60:
        raise ValidationError(
            "Delay too short! Minimum allowed: 60 seconds. "
            "However, intervals below 300s (5 min) will likely get your account restricted."
        )
    
    if delay > 31536000:  # 1 year
        raise ValidationError("Delay too long! Maximum: 1 year (31536000 seconds)")
    
    # Safety enforcement with warnings
    if delay < 300:
        raise ValidationError(
            "⚠️ DANGEROUS INTERVAL!\n\n"
            "Intervals below 300 seconds (5 minutes) will almost certainly get your "
            "Telegram account restricted or banned within hours.\n\n"
            "Recommended minimum: 600 seconds (10 minutes)\n"
            "Safe minimum: 300 seconds (5 minutes) - high risk\n\n"
            "Please choose a safer interval to protect your accounts."
        )
    
    # Apply practical limits
    return max(300, min(delay, 86400))

def validate_session_string(session_str: str) -> bool:
    """
    Validate Telethon string session format without connecting.
    
    Checks:
    - Proper length (base64 encoded session)
    - Valid base64 character set
    - Minimum entropy (not obviously fake)
    
    Args:
        session_str: Raw string session from Telethon
    
    Returns:
        True if format appears valid
    
    Raises:
        ValidationError: If format is obviously invalid
    """
    if not session_str or not isinstance(session_str, str):
        raise ValidationError("Session must be a non-empty string")
    
    # Telethon sessions are base64-encoded, typically 300-500 chars
    if len(session_str) < 100 or len(session_str) > 1000:
        raise ValidationError(
            f"Session length invalid ({len(session_str)} chars). "
            "Valid Telethon sessions are typically 300-500 characters."
        )
    
    # Check for base64 character set
    valid_chars = set(string.ascii_letters + string.digits + '+/=\\')
    if not all(c in valid_chars for c in session_str):
        raise ValidationError("Session contains invalid characters. Must be base64-encoded.")
    
    # Check for obvious fake patterns
    if session_str.startswith("1") and len(session_str) == 1:
        raise ValidationError("Invalid session format. Appears to be placeholder value.")
    
    if "invalid" in session_str.lower() or "test" in session_str.lower():
        raise ValidationError("Session contains test/invalid markers")
    
    return True

def validate_username(username: str) -> Tuple[bool, str]:
    """
    Validate Telegram username format.
    
    Rules:
    - 5-32 characters
    - Only a-z, 0-9, and underscore
    - Must start with letter
    - Cannot end with underscore
    - Cannot have consecutive underscores
    
    Args:
        username: Telegram username (with or without @)
    
    Returns:
        Tuple of (is_valid: bool, normalized_username: str without @)
    
    Raises:
        ValidationError: With specific format violation
    """
    # Remove @ prefix if present
    if username.startswith('@'):
        username = username[1:]
    
    if not username:
        raise ValidationError("Username cannot be empty")
    
    if len(username) < 5:
        raise ValidationError("Username too short (minimum 5 characters)")
    
    if len(username) > 32:
        raise ValidationError("Username too long (maximum 32 characters)")
    
    if not username[0].isalpha():
        raise ValidationError("Username must start with a letter")
    
    if username.endswith('_'):
        raise ValidationError("Username cannot end with underscore")
    
    if '__' in username:
        raise ValidationError("Username cannot contain consecutive underscores")
    
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        raise ValidationError(
            "Username can only contain letters, numbers, and underscores"
        )
    
    return True, username.lower()

def is_suspicious_content(text: str) -> Tuple[bool, Optional[str]]:
    """
    Detect potentially suspicious content that might trigger Telegram restrictions.
    
    Scans for:
    - Cryptocurrency scam patterns
    - Phishing indicators
    - Excessive promotional language
    - Blacklisted domains/keywords
    
    Returns:
        Tuple of (is_suspicious: bool, reason: Optional[str])
    """
    text_lower = text.lower()
    
    # Crypto scam patterns
    crypto_scams = [
        r'(?i)double.*your.*bitcoin',
        r'(?i)send.*crypto.*get.*back',
        r'(?i)free.*eth.*btc.*claim',
        r'(?i)guaranteed.*returns.*crypto',
        r'(?i)private.*key.*wallet',
    ]
    
    for pattern in crypto_scams:
        if re.search(pattern, text_lower):
            return True, "Cryptocurrency scam pattern detected"
    
    # Phishing indicators
    phishing = [
        r'(?i)verify.*account.*link',
        r'(?i)urgent.*security.*alert',
        r'(?i)your.*account.*suspended',
        r'(?i)click.*to.*secure.*account',
    ]
    
    for pattern in phishing:
        if re.search(pattern, text_lower):
            return True, "Phishing pattern detected"
    
    # Excessive promotional language
    promo_words = ['free', 'win', 'prize', 'gift', 'offer', 'limited', 'urgent', 'act now']
    promo_count = sum(1 for word in promo_words if word in text_lower)
    if promo_count >= 4 and len(text.split()) < 30:
        return True, "Excessive promotional language (spam risk)"
    
    return False, None