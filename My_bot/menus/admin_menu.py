from telegram import InlineKeyboardMarkup, InlineKeyboardButton


def get_admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟡 Paid / To Deliver", callback_data="admin_paid:0")],
        [InlineKeyboardButton("📦 Delivered", callback_data="admin_delivered:0")],
        [InlineKeyboardButton("⬅ Back to Main", callback_data="back_main")],
    ])


def get_admin_list_nav(kind: str, page: int, has_prev: bool, has_next: bool) -> InlineKeyboardMarkup:
    rows = []
    nav = []
    if has_prev:
        nav.append(InlineKeyboardButton("⬅ Prev", callback_data=f"{kind}:{page-1}"))
    if has_next:
        nav.append(InlineKeyboardButton("Next ➡", callback_data=f"{kind}:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("⬅ Admin Menu", callback_data="admin_menu")])
    return InlineKeyboardMarkup(rows)
