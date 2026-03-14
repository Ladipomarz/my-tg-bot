from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
import asyncio
import os
from io import BytesIO
from telegram import InputFile
# Import your safe_send and whatever cleanup tools you use
#from utils.helper import safe_send, delete_message
import httpx
from config import SMSA_API_KEY,ADMIN_IDS
import httpx
from telegram import Update
from utils.auto_delete import safe_delete_user_message
from providers.sms_activate import get_or_fetch_country_services
from utils.db import get_display_services,build_global_services_txt_bytes,build_live_country_list_txt_bytes


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


# Inside handlers/global_flow.py
# In handlers/global_flow.py
from providers.sms_activate import get_or_fetch_country_services

async def handle_global_country_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    
    # 🛡️ THE GATEKEEPER
    if user_id != int(ADMIN_IDS):
        # This is what everyone ELSE sees
        await query.answer("🚧 Global numbers are coming soon!", show_alert=True)
        return
    
    await query.answer()
    
    country_id = int(query.data.split('_')[2]) # e.g., 'g_country_3' -> 3
    
    # Save selection to user memory
    context.user_data['is_global_flow'] = True
    context.user_data['global_country_id'] = country_id
    
    # 1. Start the 'Check-then-Fetch' process
    # If the DB is fresh, this finishes in milliseconds.
    # If the DB is old, it shows the user it's working.
    success = await get_or_fetch_country_services(country_id)
    
    if success:
        # 2. Open your existing Service List!
        # Your service list UI just needs to be told: "Pull from global_services table"
        from handlers.servicelist import show_service_list
        await show_service_list(update, context)
    else:
        await query.message.reply_text("❌ Failed to synchronize global services. Please try again.")


async def handle_other_countries_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # 1. Show loading status
    loading = await query.message.reply_text("🔄 **Syncing Global Country List...**", parse_mode="Markdown")

    # 2. Fetch and build the .txt in memory
    data_bytes, filename = await build_live_country_list_txt_bytes()
    bio = BytesIO(data_bytes)
    bio.name = filename

    # 3. Send it to the user
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=InputFile(bio, filename=filename),
        caption=(
            "✅ **Master List Synced!**\n\n"
            "Open the file above, find your country, and **reply with its ID number** (e.g., 73)."
        ),
        parse_mode="Markdown"
    )

    # 4. Set the state to catch the ID they type next
    context.user_data['otp_step'] = "awaiting_global_country_id"
    await loading.delete()        

async def process_global_country_input(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handles the user's country ID input and sends the in-memory .txt file."""
    asyncio.create_task(safe_delete_user_message(update))
    
    if not text.isdigit():
        return 

    try:
        country_id = int(text)
        context.user_data['global_country_id'] = country_id
        
        loading_msg = await update.message.reply_text("🔄 **Accessing Global Catalog...**", parse_mode="Markdown")
        
        # 1. Sync the data (Check-then-Fetch)
        success = await get_or_fetch_country_services(country_id)
        if not success:
            await loading_msg.edit_text("❌ Service currently unavailable for this country. Try another ID.")
            return

        # 2. Pull data from DB
        services = get_display_services(is_global=True, country_id=country_id)
        
        # 3. Map IDs for the next step (ID -> Service Code)
        id_map = {str(i+100): s[3] for i, s in enumerate(services)}
        context.user_data['global_id_map'] = id_map
        
        # 4. Generate the In-Memory .txt File
        data_bytes, filename = build_global_services_txt_bytes(country_id, services)
        bio = BytesIO(data_bytes)
        bio.name = filename
        
        # 5. Send the File
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=InputFile(bio, filename=filename),
            caption="✅ **Catalog Generated!**\n\nReply to this message with the **ID number** of the service you want.",
            parse_mode="Markdown"
        )
        
        context.user_data['otp_step'] = "awaiting_global_service_id"
        await loading_msg.delete()

    except Exception as e:
        print(f"CRITICAL ERROR in Global Flow: {e}") 
        if 'loading_msg' in locals():
            await loading_msg.edit_text("⚠️ An error occurred while generating the catalog. Please try again.")