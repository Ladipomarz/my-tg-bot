from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
import asyncio
import os
from telegram import InputFile
# Import your safe_send and whatever cleanup tools you use
#from utils.helper import safe_send, delete_message
import httpx
from config import SMSA_API_KEY
import httpx

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
async def handle_global_country_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    country_id = int(query.data.split('_')[2])
    
    # 1. Display loading state
    msg = await query.edit_message_text("🔄 <b>Fetching live global prices...</b>", parse_mode="HTML")

    # 2. Execute the fetch
    success = await fetch_and_save_global_services(country_id)
    
    if success:
        await msg.edit_text(f"✅ Updated prices for Country {country_id}. Opening service list...")
        # NEXT: Call your existing service list UI here
    else:
        await msg.edit_text("❌ Failed to fetch services. Please try again.")


async def handle_more_countries_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggered by callback_data='g_country_more'"""
    query = update.callback_query
    await query.answer()
    
    # 1. Delete the inline menu to keep the chat clean
    try:
        await query.message.delete()
    except Exception:
        pass
        
    # 2. Send the temporary loading text
    loading_msg = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="📥 Generating Global Country List..."
    )
    
    # 3. Upload the PDF (You will need a dummy PDF named 'Country_Codes.pdf' in your bot folder for now)
    pdf_path = "Country_Codes.pdf" 
    
    try:
        with open(pdf_path, "rb") as pdf_file:
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=InputFile(pdf_file, filename="Underground_Box_Country_IDs.pdf"),
                caption=(
                    "🌍 **Full Country Catalog**\n\n"
                    "Please open the document to find your desired country.\n\n"
                    "👇 **Reply to this message with the numeric ID of the country.**\n"
                    "*(Example: For Brazil, type 73)*"
                ),
                parse_mode="Markdown"
            )
        
        # Delete the "Generating..." message
        await loading_msg.delete()
        
        # 4. Set the trapdoor in the text router!
        context.user_data['otp_step'] = "awaiting_global_country_id"
        
    except FileNotFoundError:
        await loading_msg.edit_text("❌ PDF file not found. Please contact admin.")