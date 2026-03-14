from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
# Import your safe_send and whatever cleanup tools you use
from utils.helper import safe_send, delete_message

async def handle_global_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggered by callback_data='other_countries_start'"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [
            InlineKeyboardButton("💬 Text Verification", callback_data="g_type_text"),
            InlineKeyboardButton("📞 Voice", callback_data="g_type_voice")
        ],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="main_menu")]
    ]
    
    text = "🌍 **Global Services**\n\nWhat type of service do you need?"
    
    # Using your standard edit/safe_send flow
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_global_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggered by callback_data='g_type_text' or 'g_type_voice'"""
    query = update.callback_query
    await query.answer()
    
    # Save the type in user_data
    service_type = query.data.split('_')[2] # Extracts 'text' or 'voice'
    context.user_data['global_service_type'] = service_type
    
    keyboard = [
        [
            InlineKeyboardButton("⏱ One-Time (OTP)", callback_data="g_dur_otp"),
            InlineKeyboardButton("📅 Rental", callback_data="g_dur_rental")
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="other_countries_start")]
    ]
    
    await query.edit_message_text("How long do you need this number for?", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_global_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggered by callback_data='g_dur_otp' or 'g_dur_rental'"""
    query = update.callback_query
    await query.answer()
    
    # Save duration in user_data
    duration = query.data.split('_')[2] # Extracts 'otp' or 'rental'
    context.user_data['global_duration'] = duration
    
    # The 2-1-1 Grid you asked for
    keyboard = [
        [
            InlineKeyboardButton("🇨🇳 China", callback_data="g_country_3"),
            InlineKeyboardButton("🇬🇧 United Kingdom", callback_data="g_country_15")
        ],
        [InlineKeyboardButton("🌎 More Countries", callback_data="g_country_more")],
        [InlineKeyboardButton("🔙 Back", callback_data="g_type_text")] # Goes back to duration menu
    ]
    
    text = "🌍 **Select a Country**\n\nChoose from the quick list below, or tap 'More Countries' for the full catalog."
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_global_country_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggered by callback_data='g_country_3' or 'g_country_15'"""
    query = update.callback_query
    await query.answer()
    
    country_id = query.data.split('_')[2] # Extracts '3' or '15'
    
    # --- THE MAGIC HANDOFF ---
    # 1. We tell the bot this is a global flow
    context.user_data['is_global_flow'] = True
    context.user_data['global_country_id'] = country_id
    
    # 2. We trigger your existing Service List logic right here.
    # e.g., await show_service_list(update, context)