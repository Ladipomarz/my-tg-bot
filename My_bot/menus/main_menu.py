from telegram import ReplyKeyboardMarkup

def get_main_menu():
    buttons = [
        ["🧰 Tools", "🛒 Orders"],
        ["👤 Referral", "💵 Wallet"]
    ]

    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)
