from telegram import InlineKeyboardMarkup, InlineKeyboardButton


def get_orders_menu():
    buttons = [
        [
            InlineKeyboardButton("🆕 New Order", callback_data="orders_new"),
            InlineKeyboardButton("📂 Order History", callback_data="orders_history")
        ],
        [
            InlineKeyboardButton("Close", callback_data="back_main")
        ]
    ]

    return InlineKeyboardMarkup(buttons)


def get_pending_order_menu():
    buttons = [
        [
            InlineKeyboardButton("✅ Continue pending", callback_data="orders_continue"),
            InlineKeyboardButton("❌ Cancel pending", callback_data="orders_cancel_pending"),
        ],
        [
            InlineKeyboardButton("⬅ Back", callback_data="orders_back"),
        ]
    ]

    return InlineKeyboardMarkup(buttons)


def get_order_confirm_menu():
    """
    Global Proceed / Cancel keyboard used at the end of any tool flow.
    """
    buttons = [
        [
            InlineKeyboardButton("✅ Proceed", callback_data="orders_proceed"),
            InlineKeyboardButton("❌ Cancel", callback_data="orders_cancel"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)
