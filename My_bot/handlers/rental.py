import os
import re
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram import Update
from telegram.ext import CallbackContext
from handlers.otp_handler import send_services_txt
import logging

logger = logging.getLogger(__name__)






async def handle_rental_product_id(update: Update, context: CallbackContext):
    """
    This function is called when the user enters a valid Product ID for rental.
    It will ask for the state and then stop the flow before number reservation.
    """
    # Check if callback_query is not None
    if update.callback_query:
        product_id = update.callback_query.data.strip()  # Get Product ID from callback data

        # Ensure it's a 4-digit product ID
        if not product_id.isdigit() or len(product_id) != 4:
            await update.callback_query.edit_message_text("❌ Invalid Product ID. Please reply with the Product ID (e.g. 0123).")
            return

        # Save the Product ID in the user data
        context.user_data["otp_product_id"] = product_id

        # Ask for the state for the rental
        context.user_data["otp_step"] = "awaiting_state"
        await update.callback_query.edit_message_text(
            "Please enter the US state you want the number generated from (e.g., California)."
        )
        return
    else:
        # Handle if callback_query is missing
        await update.callback_query.edit_message_text("❌ No valid callback data received.")



async def handle_rental_state(update: Update, context: CallbackContext):
    """
    This function handles the state input for rental flow and ends the flow without number reservation.
    """
    # Get the state from the user input
    state = update.message.text.strip()

    # Save the state in user data
    context.user_data["otp_state"] = state

    # End the rental flow here without triggering number reservation
    await update.message.reply_text(
        f"✅ You have selected the state: {state}. We will now proceed without generating a number."
    )

    # End the flow for now, or optionally send further information if needed
    await update.message.reply_text("Your rental process has been completed without a number reservation.")
    return






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
