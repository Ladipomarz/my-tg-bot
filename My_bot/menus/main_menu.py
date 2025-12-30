from telegram import ReplyKeyboardMarkup

def get_main_menu():
    buttons = [
        ["🧰 Tools", "🛒 Orders"],
    ]

    return ReplyKeyboardMarkup(buttons, resize_keyboard=True, is_persistent=True,
     one_time_keyboard=False,)
