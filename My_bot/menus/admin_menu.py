from telegram import InlineKeyboardMarkup, InlineKeyboardButton

def get_admin_menu():
    buttons = [
        [
            InlineKeyboardButton("👥 Users", callback_data="admin_users"),
            InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")
        ],
        [
            InlineKeyboardButton("📂 Pending Orders", callback_data="admin_pending"),
            InlineKeyboardButton("📊 Stats", callback_data="admin_stats")
        ],
        [
            InlineKeyboardButton("⬅ Back", callback_data="back_main")
        ]
    ]

    return InlineKeyboardMarkup(buttons)
