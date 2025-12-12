from telegram import InlineKeyboardMarkup, InlineKeyboardButton

def get_wallet_menu():
    buttons = [
        [
            InlineKeyboardButton("💵 Deposit", callback_data="wallet_deposit"),
            InlineKeyboardButton("💸 History", callback_data="wallet_withdraw")
        ],
        [
            InlineKeyboardButton("📊 Balance", callback_data="wallet_balance")
        ],
        [
            InlineKeyboardButton("⬅ Back", callback_data="back_main")
        ]
    ]

    return InlineKeyboardMarkup(buttons)
