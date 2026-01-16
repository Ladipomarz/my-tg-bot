from textverified import TextVerified, NumberType, ReservationType
import os
from telegram import Update
from telegram.ext import CallbackContext
from utils.db import store_services_in_db, save_service_fetch_status, has_services_been_fetched



# Initialize TextVerified client
API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")
provider = TextVerified(api_key=API_KEY, api_username=API_USERNAME)

# Function to fetch services and pass to DB for storage
async def fetch_and_save_services():
    # Fetch the available services
    services = provider.services.list(
        number_type=NumberType.MOBILE,
        reservation_type=ReservationType.VERIFICATION
    )

    # Call to store services in DB
    await store_services_in_db(services)
    
    # Mark the service list as fetched
    save_service_fetch_status()

    print("Services have been successfully fetched and stored in the database.")