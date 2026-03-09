from telegram import InlineKeyboardMarkup, InlineKeyboardButton


def get_admin_menu() -> InlineKeyboardMarkup:
    """
    Admin-only main menu.
    Visually different from user menu.
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟡 Paid / To Deliver", callback_data="admin_paid:0"),
            InlineKeyboardButton("📦 Delivered", callback_data="admin_delivered:0"),
        ],
        [
            InlineKeyboardButton("💳 Check API Balance", callback_data="admin_check_balance"),
            InlineKeyboardButton("⬅ Back to Main", callback_data="back_main"),
        ],
    ])


def get_admin_list_nav(kind: str, page: int, has_prev: bool, has_next: bool) -> InlineKeyboardMarkup:
    """
    Pagination keyboard for admin lists.
    Back + Next always on the SAME row.
    """
    rows = []

    nav_row = []
    if has_prev:
        nav_row.append(
            InlineKeyboardButton("⬅ Back", callback_data=f"{kind}:{page-1}")
        )
    if has_next:
        nav_row.append(
            InlineKeyboardButton("Next ➡", callback_data=f"{kind}:{page+1}")
        )

    if nav_row:
        rows.append(nav_row)

    rows.append([
        InlineKeyboardButton("🏠 Admin Menu", callback_data="admin_menu")
    ])

    return InlineKeyboardMarkup(rows)
