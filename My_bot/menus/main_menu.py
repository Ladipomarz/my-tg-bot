from telegram import InlineKeyboardMarkup, InlineKeyboardButton

def get_main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🧰 Tools", callback_data="tools_open"),
            InlineKeyboardButton("🛒 Orders", callback_data="orders_menu"),
        ],
        [
            InlineKeyboardButton("👤 Referral", callback_data="referral_open"),
            InlineKeyboardButton("💵 Wallet", callback_data="wallet_open"),
        ],
    ])
