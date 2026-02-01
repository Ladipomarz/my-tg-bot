import os
import re
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from handlers.otp_handler import send_services_txt
import logging

logger = logging.getLogger(__name__)



# Function to send the service list with the buttons
async def send_service_list_with_buttons(update, context):
    try:
        logger.info("Sending service list to user.")
        
        # Fetch the service list and send the .txt file using your existing function
        await send_services_txt(update, context, capability="sms")

        # Create the buttons for the user to choose
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, I have the Product ID", callback_data="otp_rental_product_id"),
                InlineKeyboardButton("🌐 Universal", callback_data="otp_rental_universal")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send the buttons after the file is sent
        if update.callback_query:
            await update.callback_query.message.reply_text("Select your option:", reply_markup=reply_markup)

        logger.info("Service list and buttons sent successfully.")

    except Exception as e:
        logger.error(f"Error sending service list with buttons: {e}")
        if update.callback_query:
            await update.callback_query.message.reply_text("An error occurred while fetching the service list.")
