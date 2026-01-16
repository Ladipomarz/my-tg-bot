from textverified import TextVerified, NumberType, ReservationType
import os
from telegram import Update
from telegram.ext import CallbackContext
from utils.db import has_services_been_fetched, store_services_in_db, save_service_fetch_status,get_connection



# Initialize TextVerified client
API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")
provider = TextVerified(api_key=API_KEY, api_username=API_USERNAME)


# Function to fetch services and pass to DB for storage
async def fetch_and_save_services():
    print("Checking if services have been fetched already...")

    # Check if services have already been fetched
    if has_services_been_fetched():  # This line calls the has_services_been_fetched() function
        print("Service list has already been fetched. Skipping fetch.")
        return  # Skip fetching if services are already saved in DB

    # Debugging line to check available methods (limit the log if necessary)
    print("Provider services object members:", dir(provider.services))  # Add this line

    # Fetch the available services
    services = provider.services.list(
        number_type=NumberType.MOBILE,
        reservation_type=ReservationType.VERIFICATION
    )

    # Optional: print a small sample or none to avoid log spamming
    print(f"Total services fetched: {len(services)}")  # Print the total count of services
    if services:
        # Only print the first 5 services to avoid spamming logs
        for i, service in enumerate(services[:5]):  # Limit to first 5 services
            print(f"Processing service {i + 1}: {service.service_name}")
        
    # Call to store services in DB
    await store_services_in_db(services)

    # Mark the service list as fetched
    save_service_fetch_status()

    print("Services have been successfully fetched and stored in the database.")
