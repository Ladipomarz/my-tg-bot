from textverified import TextVerified, NumberType, ReservationType, ReservationCapability
import os
from handlers.provider_factory import get_otp_provider
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext
from telegram.error import BadRequest




# Get API credentials from environment variables
API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")

# Initialize TextVerified client
provider = TextVerified(api_key=API_KEY, api_username=API_USERNAME)

# Function to get available services
async def get_available_services(country="USA"):
    # List available services for the given country and number type
    services = provider.services.list(
        number_type=NumberType.MOBILE,  # You can change to other types like LANDLINE if needed
        reservation_type=ReservationType.VERIFICATION
    )

    # Return available services to be shown to the user
    return services

# Correcting how the reserve_number_for_otp should handle country and service_name
async def reserve_number_for_otp(service_name: str, country="USA"):
    provider = get_otp_provider(api_key=API_KEY)  # Ensure you're using the correct API key
    # Now reserve the number using both service_name and country if necessary
    number = provider.reserve_number(service_name=service_name, country=country)
    return number

from handlers.servicelist import fetch_and_save_services  # Ensure correct import path

async def fetch_services(update: Update, context: CallbackContext):
    services = await fetch_and_save_services()  # Await the asynchronous function
    print("DEBUG services:", services)


    if not services:
        await update.message.reply_text("Failed to fetch services.")
        return

    # Create an inline keyboard with services
    keyboard = [
        [InlineKeyboardButton(service.service_name, callback_data=f"service_{service.service_name}") for service in services]
    ]

    keyboard.append([InlineKeyboardButton("⬅ Back", callback_data="tool_back_tools")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send the list of services
    await update.message.reply_text(
        "Please choose a service to reserve a number for OTP verification:",
        reply_markup=reply_markup
    )
    return services



# Show services to the user
async def show_services(update: Update, context: CallbackContext):
    services = await fetch_and_save_services()  # Fetch services

    if not services:
        await update.callback_query.edit_message_text(
            "Failed to fetch services. Please try again later."
        )
        return

    try:
        services = await fetch_and_save_services()  # Await the asynchronous function
    except Exception as e:
        await update.message.reply_text(f"Failed to fetch services: {str(e)}")
        return

    if not services:
        await update.message.reply_text("No services available.")
        return

    # Continue as before with creating the inline keyboard...


    # Create buttons for each service
    keyboard = []
    for service in services[:50]:
        service_name = service.get("service_name", "")
        if service_name:
            keyboard.append([InlineKeyboardButton(service_name, callback_data=f"service_{service_name}")])

    # Add a Back button
    keyboard.append([InlineKeyboardButton("⬅ Back", callback_data="tool_back_tools")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send the list of services
    await update.callback_query.edit_message_text(
        "Please choose a service to reserve a number for OTP verification:",
        reply_markup=reply_markup
    )
    

async def show_otp_menu(update: Update, context: CallbackContext):
    # Define the keyboard with 2 buttons in the first row and 1 button in the second row
    keyboard = [
        [InlineKeyboardButton("USA Number 🇺🇸", callback_data="tool_otp_usa"),
         InlineKeyboardButton("Other Countries 🌍", callback_data="tool_otp_other")],
        [InlineKeyboardButton("⬅ Back", callback_data="tool_back_tools")]
    ]
    
    # Create the reply markup for the inline keyboard
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Send the OTP menu with the keyboard
    await update.callback_query.edit_message_text(
        "Please choose the verification type:",
        reply_markup=reply_markup
    )

    try:
        await update.callback_query.edit_message_text(
            "Please choose the verification type:",
            reply_markup=reply_markup
        )
    except BadRequest as e:
        # Ignore only the "Message is not modified" error
        if "Message is not modified" in str(e):
            return
        raise e  # Reraise any other exceptions
    
    
async def show_usa_verification_menu(update, context):
    
    keyboard = [
            [
            InlineKeyboardButton("Text Verification", callback_data="tool_otp_usa_text"),
            InlineKeyboardButton("Voice Verification (Soon)", callback_data="tool_otp_usa_voice"),
        ],
        [InlineKeyboardButton("⬅ Back", callback_data="tool_otp")],
    ] 
    
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await update.callback_query.edit_message_text(
            "Please choose the verification method:",
            reply_markup=reply_markup
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return
        raise
    
    
async def show_rental_options(update, context, verification_type):
    # Verification type is passed to handle both Text/Voice
    keyboard = [
        [
            InlineKeyboardButton("One-Time Rental", callback_data=f"tool_otp_{verification_type}_one_time"),
            InlineKeyboardButton("Forever Rental", callback_data=f"tool_otp_{verification_type}_forever"),
        ],
        [InlineKeyboardButton("⬅ Back", callback_data="tool_otp_usa")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await update.callback_query.edit_message_text(
            f"Please choose the rental type for {verification_type} verification:\n\n"
            "Note: Duration options (e.g., 1 Month, 3 Months, etc.) are coming soon!",
            reply_markup=reply_markup
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return
        raise
