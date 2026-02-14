from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_back_button(destination: str = "dashboard") -> InlineKeyboardButton:
    """
    Generate a standardized back button.
    
    Args:
        destination: Navigation destination after back ("dashboard", "start", etc.)
    
    Returns:
        InlineKeyboardButton configured for back navigation
    """
    label_map = {
        "dashboard": "🔙 Back to Dashboard",
        "start": "🔙 Back to Start",
        "accounts": "🔙 Back to Accounts",
        "settings": "🔙 Back to Settings"
    }
    label = label_map.get(destination, "🔙 Back")
    callback = f"nav|{destination}" if destination != "dashboard" else "nav|dashboard"
    
    return InlineKeyboardButton(label, callback_data=callback)

def get_back_to_dashboard_button() -> InlineKeyboardButton:
    """Convenience function for dashboard back button"""
    return InlineKeyboardButton("🏠 Dashboard", callback_data="nav|dashboard")

def get_support_button() -> InlineKeyboardButton:
    """Standardized support contact button"""
    return InlineKeyboardButton("🛠️ Contact Support", url="https://t.me/nexaxoders")

def get_cancel_button(callback_data: str = "nav|dashboard") -> InlineKeyboardButton:
    """Standardized cancel button"""
    return InlineKeyboardButton("❌ Cancel", callback_data=callback_data)

def get_confirmation_keyboard(
    confirm_callback: str,
    cancel_callback: str = "nav|dashboard",
    confirm_text: str = "✅ Confirm",
    cancel_text: str = "❌ Cancel"
) -> InlineKeyboardMarkup:
    """
    Generate generic confirmation keyboard.
    
    Args:
        confirm_callback: Callback data for confirmation
        cancel_callback: Callback data for cancellation
        confirm_text: Display text for confirm button
        cancel_text: Display text for cancel button
    
    Returns:
        InlineKeyboardMarkup with confirmation options
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(confirm_text, callback_data=confirm_callback),
            InlineKeyboardButton(cancel_text, callback_data=cancel_callback)
        ]
    ])

def get_single_button_keyboard(
    text: str,
    callback_data: str,
    emoji: str = "✅"
) -> InlineKeyboardMarkup:
    """Generate keyboard with single prominent action button"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{emoji} {text}", callback_data=callback_data)],
        [get_back_to_dashboard_button()]
    ])

def get_two_column_keyboard(buttons: list) -> InlineKeyboardMarkup:
    """
    Generate responsive 2-column keyboard layout.
    
    Args:
        buttons: List of (label, callback_data) tuples
    
    Returns:
        InlineKeyboardMarkup with optimized 2-column layout
    """
    rows = []
    for i in range(0, len(buttons), 2):
        row = [
            InlineKeyboardButton(buttons[i][0], callback_data=buttons[i][1])
        ]
        if i + 1 < len(buttons):
            row.append(
                InlineKeyboardButton(buttons[i+1][0], callback_data=buttons[i+1][1])
            )
        rows.append(row)
    
    # Add dashboard footer
    rows.append([get_back_to_dashboard_button()])
    
    return InlineKeyboardMarkup(rows)