from textverified import TextVerified, NumberType, ReservationType
import os

from utils.db import (
    create_service_fetch_status_table,
    has_services_been_fetched,
    store_services_in_db,
    store_rental_services_in_db,
    save_service_fetch_status,
)

API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")

provider = TextVerified(api_key=API_KEY, api_username=API_USERNAME)



# ✅ THE PYTHON HACK: 
# We create a fake Enum object to bypass the SDK's missing Enum error.
# The TextVerified API expects the word "reservation" for rental lines.
class FakeRentalEnum:
    @property
    def value(self):
        return "reservation"

def fetch_and_save_services():
    create_service_fetch_status_table()

    print("Starting service fetch process...")
    print("Checking if services have been fetched...")

    if has_services_been_fetched():
        print("Service list already fetched. Skipping.")
        return

    print("Fetching One-Time Verification services...")
    verification_services = provider.services.list(
        number_type=NumberType.MOBILE,
        reservation_type=ReservationType.VERIFICATION,
    )

    print("Fetching Rental services using Enum Bypass...")
    try:
        # We pass our fake enum here to trick the SDK into building the perfect URL
        rental_services = provider.services.list(
            number_type=NumberType.MOBILE,
            reservation_type=FakeRentalEnum()
        )
        print(f"✅ Successfully downloaded {len(rental_services)} Rental services.")
    except Exception as e:
        print(f"❌ Failed to fetch rentals. Error: {e}")
        rental_services = []

    print(f"Storing {len(verification_services)} Verification and {len(rental_services)} Rental services in DB...")
    
    # Save them into their totally separate tables
    store_services_in_db(verification_services)
    
    if rental_services:
        store_rental_services_in_db(rental_services)
    
    save_service_fetch_status()
    print("✅ All services fetched + stored.")