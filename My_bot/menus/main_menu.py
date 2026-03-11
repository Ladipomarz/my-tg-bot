from telegram import ReplyKeyboardMarkup

def get_main_menu():
    buttons = [
        ["🧰 Tools", "🛒 Orders"],
         ["💰 Credit","🛠 Support"]
    ]

    return ReplyKeyboardMarkup(buttons, resize_keyboard=True,is_persistent=False,
     one_time_keyboard=False,)

from telegram import ReplyKeyboardMarkup

def get_main_menu():
    # ✅ Matches your requested layout: 2 rows of 2 buttons
    buttons = [
        ["🇺🇸 Purchase USA Number", "🌍 Purchase Non Number"],
        ["🧰 Tools", "🛒 Orders"],
        ["💰 Credit", "🛠 Support"]
    ]

    return ReplyKeyboardMarkup(
        buttons, 
        resize_keyboard=True, # ✅ Keeps buttons compact
        one_time_keyboard=False, # ✅ Keeps the menu visible after use
        is_persistent=True # ✅ Forces the '4 dots' to stay visible in modern Telegram
    )

