from telegram import ReplyKeyboardMarkup

def get_main_menu():
    buttons = [
        ["🧰 Tools", "🛒 Orders"],
         ["💰 Wallet"],["🛠 Support"]
    ]

    return ReplyKeyboardMarkup(buttons, resize_keyboard=True,
     one_time_keyboard=False,)


