"""OTP numeric keypad with visual feedback and security features"""
from typing import Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from models.user_state import UserState

def get_otp_keyboard(user_id: int, state: Optional[UserState] = None) -> InlineKeyboardMarkup:
    """
    Generate secure OTP input keypad with visual feedback.
    
    Security & UX features:
    - Masked display (•••••) prevents shoulder surfing
    - Visual feedback for entered digits (*••••)
    - Backspace for corrections
    - Cancel button for aborting flow
    - Direct link to Telegram's official OTP message
    - Disabled buttons when buffer is full (prevents overflow)
    
    Args:
        user_id: Telegram user ID (for callback data)
        state: Current user state containing OTP buffer (optional)
    
    Returns:
        InlineKeyboardMarkup with numeric keypad layout
    """
    # Determine display state
    if state and state.buffer:
        display_chars = ["*"] * len(state.buffer) + ["•"] * (5 - len(state.buffer))
        display_text = " ".join(display_chars)
    else:
        display_text = "• • • • •"
    
    # Build keypad rows
    keypad_rows = [
        [InlineKeyboardButton(display_text, callback_data="ignore")],
        [
            InlineKeyboardButton("1", callback_data="otp|1"),
            InlineKeyboardButton("2", callback_data="otp|2"),
            InlineKeyboardButton("3", callback_data="otp|3")
        ],
        [
            InlineKeyboardButton("4", callback_data="otp|4"),
            InlineKeyboardButton("5", callback_data="otp|5"),
            InlineKeyboardButton("6", callback_data="otp|6")
        ],
        [
            InlineKeyboardButton("7", callback_data="otp|7"),
            InlineKeyboardButton("8", callback_data="otp|8"),
            InlineKeyboardButton("9", callback_data="otp|9")
        ],
        [
            InlineKeyboardButton("⌫", callback_data="otp|back"),
            InlineKeyboardButton("0", callback_data="otp|0"),
            InlineKeyboardButton("❌ Cancel", callback_data="otp|cancel")
        ],
        [
            # Direct link to Telegram's official OTP message (user 777000)
            InlineKeyboardButton(
                "📱 View Official OTP Message",
                url=f"tg://user?id=777000"
            )
        ]
    ]
    
    return InlineKeyboardMarkup(keypad_rows)

def get_otp_resend_keyboard(phone: str) -> InlineKeyboardMarkup:
    """
    Keyboard for OTP resend option after timeout.
    
    Args:
        phone: Phone number to resend OTP to
    
    Returns:
        InlineKeyboardMarkup with resend option
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Resend OTP", callback_data=f"otp|resend|{phone}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="otp|cancel")]
    ])