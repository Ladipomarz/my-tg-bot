from textverified import TextVerified ,NumberType, ReservationType, ReservationCapability
import os
import os
import re
import asyncio
from telegram import Update
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from handlers.otp_handler import send_services_txt
from utils.validator import US_STATE_NAMES,suggest_us_states_full_name
import random
import requests
import httpx
import time
from utils.auto_delete import safe_send
import logging


logger = logging.getLogger(__name__)



# This is for validating the Product ID and transitioning to the next step

async def handle_rental_product_id(update: Update, context: CallbackContext):
    """
    Handles the rental product ID input and asks for the state where the rental number will be generated.
    """
    # Check if it's a callback query (which is the case when the user clicks on "Yes, I have the Product ID")
    if update.callback_query:
        context.user_data["otp_step"] = "awaiting_rental_product_id"  # Indicate that we are waiting for the product ID

        # Send the message asking for the product ID
        await update.callback_query.message.reply_text(
            "✅ Great. Please reply with the 4-digit Product ID (example: 0042)."
        )

        # Acknowledge the callback query to avoid waiting for it
        await update.callback_query.answer()
        return  # Stop here, the next step is when the user replies with the Product ID

    # If it's a regular message, we handle the product ID input
    if update.message:
        product_id = update.message.text.strip()  # Capture the Product ID

        # Validate the Product ID
        if len(product_id) in [3,4] and product_id.isdigit():
            context.user_data["otp_rental_product_id"] = product_id  # Store the rental product ID
            context.user_data["otp_step"] = "awaiting_rental_state"  # Next step: ask for the state
            
             # Ask the user if they want to select a state or not
            await ask_state_or_random(update, context)  # Call this function to ask the user for state or random selection
            
        else:
            # If the Product ID is invalid
            await update.message.reply_text("❌ Invalid Product ID. Please reply with a valid 4-digit Product ID (e.g. 0123).")


async def ask_state_or_random(update: Update, context: CallbackContext):
    """
    Ask the user if they want the number generated from a specific US state.
    """
    context.user_data["otp_step"] = "awaiting_state_or_random"
    
    # Send the prompt asking if the user wants the number from a specific state or random
    await update.message.reply_text(
        "Do you want the number to be generated from a specific US state?\n\n"
        "✅ Reply with: yes or no"
    )
    
    
    
async def handle_state_or_random(update: Update, context: CallbackContext):
    """
    Handle the user's response for state or random selection.
    """
    response = update.message.text.strip().lower()

    if response == "yes":
        # If user wants to specify the state
        context.user_data["otp_step"] = "awaiting_state"
        await update.message.reply_text(
            "Please enter the US state you want the rental number generated from (e.g., California)."
        )
    elif response == "no":
        # If user does not want to specify the state, pick a random state
        context.user_data["otp_step"] = "random_state"
        # Randomly select a state from a predefined list (or TextVerified API)
        random_state = random.choice(US_STATE_NAMES)  # Randomly select a state from the list
        context.user_data["otp_state"] = random_state

        # Proceed to final confirmation
        await final_confirmation(update, context)
    else:
        # If the input is invalid, prompt the user again
        await update.message.reply_text("❌ Please reply with either 'yes' or 'no' to confirm.")   

                        
            
async def handle_rental_state(update: Update, context: CallbackContext):
    state = update.message.text.strip()
    
    # Normalize the input state (convert to lowercase and remove extra spaces)
    state = state.lower()

    # Validate the state (match it with valid states)
    valid_states = [state.lower() for state in US_STATE_NAMES]  # Normalize all valid states to lowercase
    

    if state in valid_states:
        context.user_data["otp_state"] = state
        # Proceed to final confirmation
        await final_confirmation(update, context)
    else:
        
        await update.message.reply_text("❌ Invalid state. Please provide a valid state (e.g., California).")

        # If invalid, suggest valid states
        suggestions = suggest_us_states_full_name(state)
        suggestion_text = "Did you mean:\n" + "\n".join(suggestions) if suggestions else "❌ Invalid state. Please provide a valid state (e.g., California)."
        await update.message.reply_text(suggestion_text)


    
async def final_confirmation(update: Update, context: CallbackContext):
    """
    Display the final confirmation with the selected service, state, and price.
    """
    service = context.user_data.get("otp_service_name", "Unknown Service")
    state = context.user_data.get("otp_state", "Random")
    price = 3.00  # You can adjust this as per your service's pricing.

    confirmation_message = f"""
    FINAL CONFIRMATION:

    Service: {service}
    State: {state}
    Price: ${price}

    ⚠️ Please reply with either 'yes' or 'no' to confirm.
    """

    await update.message.reply_text(confirmation_message)
    # Handle user response for confirmation
    context.user_data["otp_step"] = "final_confirmation_step"    
    
    
async def confirm_rental(update: Update, context: CallbackContext):
    """
    Final confirmation for rental flow.
    """
    text = update.message.text.strip().lower()

    if text == "yes":
        # Proceed with fetching rental number from TextVerified API
        service = context.user_data.get("otp_service_name", "Unknown Service")
        state = context.user_data.get("otp_state", "Random")

        rental_number = fetch_rental_number_from_textverified(service, state)

        if rental_number:
            await update.message.reply_text(f"✅ Reserved number!\n\nRental Number: {rental_number}\nService: {service}\nState: {state}")
            # Proceed to further steps if needed (e.g., OTP verification or others)
        else:
            await update.message.reply_text("❌ Failed to fetch rental number. Please try again later.")
        
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
        
        await safe_send(update, context, "Select your option:", reply_markup=reply_markup)

        logger.info("Service list and buttons sent successfully.")

    except Exception as e:
        logger.error(f"Error sending service list with buttons: {e}")
        if update.callback_query:
            await update.callback_query.message.reply_text("An error occurred while fetching the service list.")



###FETCH FLOW 


# Initialize the TextVerified client
API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")

provider = TextVerified(api_key=API_KEY, api_username=API_USERNAME)

async def reserve_rental_number(
    service_name: str,
    state: str | None,
    service_not_listed_name: str | None = None,
):
    """
    Creates a rental number and returns the verification object.
    TextVerified SDK handles reservations differently for rental numbers.
    """
    def _do():
        kwargs = {
            "service_name": service_name,
            "capability": ReservationCapability.SMS,
            "reservation_type": "rental",  # Specify that it's a rental number
        }

        # For "not listed" flow (for example, when the service is not listed on the API)
        if service_not_listed_name and service_name == "servicenotlisted":
            kwargs["service_not_listed_name"] = service_not_listed_name

        # If state is provided, map it to area codes for rental
        if state:
            acs = _area_codes_for_state(state)
            if acs:
                kwargs["area_code_select_option"] = acs[:15]  # Pick the first 15 area codes

        # Make the reservation
        return provider.verifications.create(**kwargs)

    return await asyncio.to_thread(_do)


async def fetch_rental_number_from_textverified(service_name: str, state: str):
    """
    Fetches a rental number for a service from TextVerified API.
    """
    try:
        rental_number_verification = await reserve_rental_number(service_name, state)
        rental_number = rental_number_verification.get("phone_number")  # Extract the number
        return rental_number

    except Exception as e:
        print(f"Error fetching rental number: {e}")
        return None


async def call_rental_number(update: Update, context: CallbackContext):
    """
    Function to trigger rental number reservation and send to user.
    """
    service_name = context.user_data.get("otp_service_name", "Unknown Service")  # Example, dynamically fetch this
    state = context.user_data.get("otp_state", "Random")  # Example, dynamically fetch state or set as "Random"
    
    # Fetch rental number
    rental_number = await fetch_rental_number_from_textverified(service_name, state)

    if rental_number:
        await update.message.reply_text(f"✅ Reserved number!\n\nRental Number: {rental_number}\nService: {service_name}\nState: {state}")
    else:
        await update.message.reply_text("❌ Failed to fetch rental number. Please try again later.")
