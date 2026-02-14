from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_delay_keyboard(current_delay: int = 600) -> InlineKeyboardMarkup:
    """
    Generate delay selection keyboard with risk visualization.
    
    Risk indicators:
    🔴 < 300s  - High risk (aggressive)
    🟡 300-600s - Medium risk (balanced)
    🟢 > 600s  - Low risk (conservative)
    
    Design rationale:
    - Visual risk indicators help users make safe choices
    - Current selection highlighted with checkmark
    - Recommended option emphasized
    - Clear safety warnings in parent handler
    
    Args:
        current_delay: Current delay setting in seconds
    
    Returns:
        InlineKeyboardMarkup with delay options
    """
    def get_emoji_for_delay(delay: int) -> str:
        """Return risk indicator emoji based on delay value"""
        if delay < 300:
            return "🔴"
        elif delay <= 600:
            return "🟡"
        else:
            return "🟢"
    
    def get_checkmark(delay: int) -> str:
        """Return checkmark if this is the current selection"""
        return " ✅" if delay == current_delay else ""
    
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"5 min {get_emoji_for_delay(300)}{get_checkmark(300)}",
                callback_data="setdelay|300"
            ),
            InlineKeyboardButton(
                f"10 min {get_emoji_for_delay(600)}{get_checkmark(600)}",
                callback_data="setdelay|600"
            )
        ],
        [
            InlineKeyboardButton(
                f"20 min {get_emoji_for_delay(1200)}{get_checkmark(1200)}",
                callback_data="setdelay|1200"
            )
        ],
        [
            InlineKeyboardButton("⚠️ Safety Guidelines", callback_data="delay|guidelines")
        ],
        [
            InlineKeyboardButton("🔙 Back to Dashboard", callback_data="nav|dashboard")
        ]
    ])

def get_delay_guidelines_keyboard() -> InlineKeyboardMarkup:
    """Keyboard with safety guidelines for delay settings"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ I Understand", callback_data="delay|nav")
        ],
        [
            InlineKeyboardButton("🔙 Back to Settings", callback_data="delay|nav")
        ]
    ])