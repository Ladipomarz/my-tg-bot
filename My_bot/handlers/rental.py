import os
import re
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram import Update
from telegram.ext import CallbackContext
from handlers.otp_handler import send_services_txt
import logging

logger = logging.getLogger(__name__)




async def ask_for_rental_product_id(update: Update, context: CallbackContext):
    """
    Ask the user for the 4-digit Product ID in the rental flow.
    """
    context.user_data["otp_step"] = "awaiting_product_id"
    await update.callback_query.edit_message_text(
        "✅ Great. Please reply with the 4-digit Product ID (example: 0042)."
    )
    
    
async def handle_rental_product_id(update: Update, context: CallbackContext):
    """
    Handle the product ID input for rental.
    """
    product_id = update.callback_query.message.text.strip()  # Get the Product ID from the callback message

    if not product_id.isdigit() or len(product_id) != 4:
        await update.message.reply_text("❌ Invalid Product ID. Please reply with the Product ID (e.g. 0123).")
        return

    # Save the Product ID in the user data
    context.user_data["otp_product_id"] = product_id

    # Ask for the state for the rental
    context.user_data["otp_step"] = "awaiting_state"
    await update.message.reply_text(
        "Please enter the US state you want the number generated from (e.g., California)."
    )



async def handle_rental_state(update: Update, context: CallbackContext):
    """
    Handle the state input for rental.
    """
    state = update.message.text.strip()

    # Save the state in user data
    context.user_data["otp_state"] = state

    # Show final confirmation
    service = context.user_data.get("otp_service_name", "Unknown Service")
    price = 3.00  # This would typically be dynamic, depending on the service

    confirmation_message = f"""
    FINAL CONFIRMATION:

    Service: {service}
    State: {state}
    Price: ${price}

    ⚠️Please reply with either yes or no to confirm.
    """

    await update.message.reply_text(confirmation_message)
    
    
async def confirm_rental(update: Update, context: CallbackContext):
    """
    Final confirmation for rental flow.
    """
    text = update.message.text.strip().lower()

    if text == "yes":
        # Proceed with the rental logic (without reserving the number)
        await update.message.reply_text("✅ Reserved number! We will now proceed with the rental.")

        # You can store or process additional rental data here if necessary
    elif text == "no":
        await update.message.reply_text("❌ Rental not confirmed. The process has been cancelled.")
    else:
        await update.message.reply_text("❌ Invalid input. Please reply with 'yes' or 'no' to confirm.")




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
