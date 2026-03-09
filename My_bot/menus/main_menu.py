from telegram import ReplyKeyboardMarkup

def get_main_menu():
    buttons = [
        ["🧰 Tools", "🛒 Orders"],
         ["💰 Credit","🛠 Support"]
    ]

    return ReplyKeyboardMarkup(buttons, resize_keyboard=True,is_persistent=False,
     one_time_keyboard=False,)


