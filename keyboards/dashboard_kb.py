from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_dashboard_keyboard() -> InlineKeyboardMarkup:
    """
    Generate the main dashboard keyboard with logical grouping:
    
    Column 1 (Account Management):
    - Add Accounts
    - My Accounts
    - Delete Accounts
    
    Column 2 (Campaign Management):
    - Set Ad Message
    - Set Time Interval
    - Start/Stop Ads
    
    Footer:
    - Analytics (performance tracking)
    - Auto Reply (future feature)
    - Back to Welcome
    
    Design rationale:
    - 2-column layout optimizes screen real estate on mobile
    - Related functions grouped vertically for muscle memory
    - Critical actions (Start/Stop) use action-oriented emojis
    - Safety features (Analytics) prominently placed
    """
    return InlineKeyboardMarkup([
        # Account Management Column
        [
            InlineKeyboardButton("📱 Add Accounts", callback_data="acc|add"),
            InlineKeyboardButton("📋 My Accounts", callback_data="acc|list|0")
        ],
        # Campaign Configuration Column
        [
            InlineKeyboardButton("💬 Set Ad Message", callback_data="ad|set"),
            InlineKeyboardButton("⏱️ Set Interval", callback_data="delay|nav")
        ],
        # Campaign Control Row
        [
            InlineKeyboardButton("▶️ Start Ads", callback_data="camp|start"),
            InlineKeyboardButton("⏹️ Stop Ads", callback_data="camp|stop")
        ],
        # Utility Row
        [
            InlineKeyboardButton("🗑️ Delete Accounts", callback_data="acc|del"),
            InlineKeyboardButton("📊 Analytics", callback_data="stat|main")
        ],
        # Feature Row & Navigation
        [
            InlineKeyboardButton("🤖 Auto Reply", callback_data="feature|auto"),
            InlineKeyboardButton("🔙 Back", callback_data="nav|start")
        ]
    ])