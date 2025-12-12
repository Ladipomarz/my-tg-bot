from telegram import InlineKeyboardMarkup, InlineKeyboardButton

def get_referral_menu():
    buttons = [
        [
            InlineKeyboardButton("📨 Invite Friend", callback_data="ref_invite"),
            InlineKeyboardButton("💰 My Earnings", callback_data="ref_earnings")
        ],
        [
            InlineKeyboardButton("⬅ Back", callback_data="back_main")
        ]
    ]

    return InlineKeyboardMarkup(buttons)
