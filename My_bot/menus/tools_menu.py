from telegram import InlineKeyboardMarkup, InlineKeyboardButton




def get_tools_inline():
    buttons = [
        [
            InlineKeyboardButton("SSN Services", callback_data="tool_ssn_services"),
            InlineKeyboardButton("⬅ Back", callback_data="back_main"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_ssn_services_menu():
    buttons = [
        [
            InlineKeyboardButton("🔍 SSN Lookup", callback_data="tool_ssn_lookup"),
            InlineKeyboardButton("SSN Magic", callback_data="tool_ssn_magic"),
        ],
        [
            InlineKeyboardButton("⬅ Back", callback_data="tool_back_tools"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)
