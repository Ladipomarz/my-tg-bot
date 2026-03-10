from telegram import InlineKeyboardMarkup, InlineKeyboardButton

def get_tools_inline():
    buttons = [
        [
            InlineKeyboardButton("MSN Services", callback_data="tool_msn_services"),
             InlineKeyboardButton("Esim", callback_data="esim_services"),
        ],

        [   InlineKeyboardButton("🖥️RDP", callback_data="tool_rdp"),
            InlineKeyboardButton("OTP Verification", callback_data="tool_otp_usa"),
            ],
        
        [InlineKeyboardButton("📣 Social Services", callback_data="social_menu")],
        [InlineKeyboardButton("Close", callback_data="back_main")],
    ]
    return InlineKeyboardMarkup(buttons)

def get_msn_services_menu():
    buttons = [
        [
            InlineKeyboardButton("🔍 MSN Lookup", callback_data="tool_msn_lookup"),
            InlineKeyboardButton("MSN Magic", callback_data="tool_msn_magic"),
        ],
        [
            InlineKeyboardButton("⬅ Back", callback_data="tool_back_tools"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_esim_duration_menu():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📅 1 Month", callback_data="esim_duration:1m"),
                InlineKeyboardButton("📅 3 Months", callback_data="esim_duration:3m"),
            ],
            [
                InlineKeyboardButton("📅 1 Year", callback_data="esim_duration:1y"),
                InlineKeyboardButton("⬅️ Back", callback_data="tool_back_tools"),
            ],
        ]
    )
