from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from utils.db import get_rental_by_id, debit_balance, extend_rental, cancel_rental  # Import your DB functions
from menus.main_menu import get_main_menu  # For the main menu after rental
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Step 1: Send service list
async def send_service_list_rental(update, context, capability="sms"):
    # Send the service list as a .txt file (SMS or Voice based on capability)
    await send_services_txt(update, context, capability=capability)

# Step 2: Show rental buttons after service list
async def show_rental_buttons(update, context):
    keyboard = [
        [InlineKeyboardButton("Yes, I have the product", callback_data="otp_rental_have_product")],
        [InlineKeyboardButton("All Services (Universal)", callback_data="otp_rental_all_services")]
    ]
    await update.message.reply_text(
        "Please select one of the options below:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )



# Step 4: Fetch rental number for universal service
async def fetch_rental_number_for_rental():
    rental_number = await reserve_number_for_rental(service="sms")  # Or "voice"
    return rental_number

# Optional: Process the rental confirmation if user provides the product ID
async def handle_product_id(update, context):
    product_id = update.message.text.strip()  # Assuming the product ID is provided by the user
    rental = get_rental_by_id(product_id)  # Example DB call to fetch rental info by product ID
    if rental:
        await update.message.reply_text(f"Rental found! Your product ID: {product_id}")
    else:
        await update.message.reply_text("❌ Invalid Product ID. Please try again.")


def test_get_rental_by_id(rental_id):
    rental = get_rental_by_id(rental_id)
    if rental:
        print(f"Rental found: {rental}")
    else:
        print(f"No rental found with ID: {rental_id}")

# Call the test function with an existing rental_id
test_get_rental_by_id(1)
