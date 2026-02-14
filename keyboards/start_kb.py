from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_start_keyboard() -> InlineKeyboardMarkup:
    """
    Generate the initial welcome screen keyboard with primary navigation options.
    
    Design principles:
    - Primary action (Dashboard) prominently placed at top
    - Support resources easily accessible
    - Clear visual hierarchy with emoji indicators
    - Branded footer for attribution
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Dashboard", callback_data="nav|dashboard")],
        [
            InlineKeyboardButton("📢 Updates", url="https://t.me/testttxs"),
            InlineKeyboardButton("🛠️ Support", url="https://t.me/nexaxoders")
        ],
        [InlineKeyboardButton("📘 How to Use", callback_data="nav|howto")],
        [InlineKeyboardButton("⚡ Powered by @NexaCoders", url="https://t.me/nexaxoders")]
    ])

def get_welcome_keyboard() -> InlineKeyboardMarkup:
    """Alternative welcome keyboard with stronger CTA focus"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✨ Start Broadcasting", callback_data="nav|dashboard")],
        [InlineKeyboardButton("❓ Need Help?", url="https://t.me/nexaxoders")]
    ])