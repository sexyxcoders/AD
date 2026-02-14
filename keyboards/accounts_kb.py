from typing import List, Dict
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_accounts_keyboard(accounts: List[Dict], page: int = 0) -> InlineKeyboardMarkup:
    """
    Generate paginated account list keyboard.
    
    Features:
    - Visual status indicators (🟢/🔴)
    - Phone number masking (••••1234)
    - Intelligent pagination boundaries
    - Empty state handling (caller should handle)
    
    Args:
        accounts: List of account documents from database
        page: Current page index (0-based)
    
    Returns:
        InlineKeyboardMarkup with paginated account list
    """
    buttons = []
    page_size = 5
    start_idx = page * page_size
    end_idx = start_idx + page_size
    
    # Account list rows
    for acc in accounts[start_idx:end_idx]:
        status_emoji = "🟢" if acc.get("active", False) else "🔴"
        phone = acc["phone"]
        masked_phone = f"••••{phone[-4:]}" if len(phone) >= 4 else phone
        
        buttons.append([
            InlineKeyboardButton(
                f"{status_emoji} {masked_phone}",
                callback_data=f"acc|detail|{acc['_id']}"
            )
        ])
    
    # Pagination controls
    nav_row = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton("⬅️ Previous", callback_data=f"acc|list|{page-1}")
        )
    if end_idx < len(accounts):
        nav_row.append(
            InlineKeyboardButton("Next ➡️", callback_data=f"acc|list|{page+1}")
        )
    
    if nav_row:
        buttons.append(nav_row)
    
    # Footer navigation
    buttons.append([
        InlineKeyboardButton("🏠 Dashboard", callback_data="nav|dashboard")
    ])
    
    return InlineKeyboardMarkup(buttons)

def get_account_detail_keyboard(acc_id: str, phone: str) -> InlineKeyboardMarkup:
    """
    Generate account detail view keyboard.
    
    Layout:
    - Primary action: Delete Account (destructive action)
    - Secondary actions: Navigation back to list/dashboard
    - Visual hierarchy with emoji indicators
    
    Args:
        acc_id: Account document ID
        phone: Account phone number (for display purposes)
    
    Returns:
        InlineKeyboardMarkup for account detail view
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ Delete Account", callback_data=f"acc|delete|{acc_id}")],
        [InlineKeyboardButton("🔙 Back to List", callback_data="acc|list|0")],
        [InlineKeyboardButton("🏠 Dashboard", callback_data="nav|dashboard")]
    ])

def get_delete_confirmation_keyboard(acc_id: str) -> InlineKeyboardMarkup:
    """
    Generate account deletion confirmation keyboard.
    
    Safety features:
    - Explicit confirmation required (no accidental deletes)
    - Clear visual distinction between confirm/cancel
    - Destructive action marked with warning emoji
    
    Args:
        acc_id: Account document ID to delete
    
    Returns:
        InlineKeyboardMarkup with confirmation options
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, Delete", callback_data=f"acc|confirm_del|{acc_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data="nav|dashboard")
        ]
    ])

def get_empty_accounts_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for empty account state with helpful CTA"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Add Your First Account", callback_data="acc|add")],
        [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="nav|dashboard")]
    ])