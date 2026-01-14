from textverified import TextVerified, NumberType, ReservationType, ReservationCapability
import os
from handlers.provider_factory import get_otp_provider
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext
from telegram.error import BadRequest
API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")




async def otp_verification_handler(update: Update, context: CallbackContext, method: str):
    # Show buttons for choosing between USA and Other Countries
    keyboard = [
        [
            InlineKeyboardButton("🇺🇸 USA", callback_data="otp_usa"),
            InlineKeyboardButton("🌍 Other Countries", callback_data="otp_other_country")
        ],
        [InlineKeyboardButton("⬅ Back", callback_data="otp_back_verification")]
    ]
    await _edit(update, "Please choose your region:", keyboard)



async def show_usa_verification_menu(update: Update, context: CallbackContext):
    """
    This function sends a menu for USA verification options after the user clicks 'USA Number 🇺🇸'
    It gives options for Text and Voice Verification.
    """
    keyboard = [
        [
            InlineKeyboardButton("Text Verification", callback_data="tool_otp_usa_text"),
            InlineKeyboardButton("Voice Verification (Coming Soon)", callback_data="tool_otp_usa_voice")
        ],
        [InlineKeyboardButton("⬅ Back", callback_data="otp_back_verification")],  # Back button to the OTP menu
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
        raise  # Reraise if any other error happens  


# Initialize TextVerified client
provider = TextVerified(api_key=API_KEY, api_username=API_USERNAME)

# Correcting how the reserve_number_for_otp should handle country and service_name
async def reserve_number_for_otp(service_name: str, country="USA"):
    provider = get_otp_provider(api_key=API_KEY)  # Ensure you're using the correct API key
    # Now reserve the number using both service_name and country if necessary
    number = provider.reserve_number(service_name=service_name, country=country)
    return number


from handlers.servicelist import fetch_and_save_services  # Ensure correct import path

# ---------- OTP MENUS ----------

async def otp_usa_one_time_or_rental_menu(update, context, method: str):
    keyboard = [
        [
            InlineKeyboardButton(
                "One-Time",
                callback_data=f"otp_usa_{method}_one_time",
            ),
            InlineKeyboardButton(
                "Rental",
                callback_data=f"otp_usa_{method}_rental",
            ),
        ],
        [InlineKeyboardButton("⬅ Back", callback_data="otp_back_usa_verif_type")],
    ]
    await _edit(update, "Choose rental type:", keyboard)


async def otp_usa_rental_type_menu(update, context, method: str):
    keyboard = [
        [
            InlineKeyboardButton(
                "Monthly Rental",
                callback_data=f"otp_usa_{method}_rental_monthly",
            ),
            InlineKeyboardButton(
                "Forever Rental",
                callback_data=f"otp_usa_{method}_rental_forever",
            ),
        ],
        [InlineKeyboardButton("⬅ Back", callback_data="otp_back_usa_one_time_rental")],
    ]
    await _edit(update, "Choose rental duration:", keyboard)


async def otp_usa_monthly_duration_menu(update, context, method: str):
    keyboard = [
        [
            InlineKeyboardButton(
                "1 Month", callback_data=f"otp_usa_{method}_rental_monthly_1m"
            ),
            InlineKeyboardButton(
                "2 Months", callback_data=f"otp_usa_{method}_rental_monthly_2m"
            ),
        ],
        [
            InlineKeyboardButton(
                "3 Months", callback_data=f"otp_usa_{method}_rental_monthly_3m"
            )
        ],
        [InlineKeyboardButton("⬅ Back", callback_data="otp_back_usa_rental_type")],
    ]
    await _edit(update, "Select duration:", keyboard)
    
  
# ---------- INTERNAL HELPER ----------

async def _edit(update, text, keyboard):
    try:
        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return
        raise

