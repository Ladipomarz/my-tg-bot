from textverified import TextVerified, NumberType, ReservationType
import os
from telegram import Update
from telegram.ext import CallbackContext
BASE_DIR = os.path.dirname(__file__)
OUT_PATH = os.path.join(BASE_DIR, "services.txt")



# Initialize TextVerified client
API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")
provider = TextVerified(api_key=API_KEY, api_username=API_USERNAME)

# Function to fetch and save available services to 'services.txt'
async def fetch_and_save_services():
    # Fetch the available services
    services = provider.services.list(
        number_type=NumberType.MOBILE,
        reservation_type=ReservationType.VERIFICATION
    )

    # If no services are available, print a message and return
    if not services:
        print("No services available.")
        return

    # Save services to 'services.txt' file
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("Available Services for OTP Verification:\n\n")
        for i, service in enumerate(services[:5], 1):  # Limit to first 5 services
            f.write(f"{i}. {service.service_name}\n")

    print("Services saved to 'services.txt'.")
    return services
    

