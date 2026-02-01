import os
import re
import asyncio
from telegram import Update
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from handlers.otp_handler import send_services_txt
import logging


logger = logging.getLogger(__name__)



async def handle_rental_product_id(update: Update, context: CallbackContext):
    """
    Handles the rental product ID input and asks for the state where the rental number will be generated.
    """
    # Check if the callback query exists
    if update.callback_query:
        context.user_data["otp_step"] = "awaiting_rental_product_id"  # Indicate that we are waiting for the product ID

        # Send the message asking for the product ID
        await update.callback_query.message.reply_text(
            "✅ Great. Please reply with the 4-digit Product ID (example: 0042)."
        )
        
        # Acknowledge the callback query to avoid waiting for it
        await update.callback_query.answer()
        
        return  # Stop here, the next step is when the user replies with the Product ID

# Handling the user's reply for the Product ID
async def handle_product_id_reply(update: Update, context: CallbackContext):
    """
    Handles the user's reply with the Product ID.
    """
    # Get the Product ID from the user's reply
    product_id = update.message.text.strip()  # Capture the Product ID from the reply

    # Validate the Product ID
    if len(product_id) == 4 and product_id.isdigit():
        context.user_data["otp_rental_product_id"] = product_id  # Store the rental product ID
        context.user_data["otp_step"] = "awaiting_rental_state"  # Next step: ask for the state
        

        logger.debug(f"otp_step updated to: {context.user_data['otp_step']}")
        
        # Ask the user for the state
        await update.message.reply_text(
            "Please enter the US state you want the rental number generated from (e.g., California)."
        )
    else:
        # If the Product ID is invalid
        await update.message.reply_text("❌ Invalid Product ID. Please reply with a valid 4-digit Product ID (e.g. 0123).")

            


async def handle_rental_state(update: Update, context: CallbackContext):
    logger.debug("Entering handle_rental_state function.")

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
