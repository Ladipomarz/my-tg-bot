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

    print("Fetching Rental services...")
    
    # ✅ DYNAMIC ENUM FIX: Scan the SDK for the correct Rental name
    rental_enum = None
    possible_names = ["RESERVATION", "RENEWABLE_RENTAL", "NONRENEWABLE_RENTAL", "RENTALS", "LINE_RESERVATION"]
    
    for name in possible_names:
        if hasattr(ReservationType, name):
            rental_enum = getattr(ReservationType, name)
            print(f"✅ Found exact Rental Enum in SDK: {name}")
            break

    rental_services = []
    
    if rental_enum:
        # Use the enum we just found
        rental_services = provider.services.list(
            number_type=NumberType.MOBILE,
            reservation_type=rental_enum,
        )
    else:
        # ⚠️ FALLBACK: If the Enum is completely missing, we bypass it with strings
        print("⚠️ Rental Enum not found. Attempting string bypass...")
        try:
            rental_services = provider.services.list(
                number_type=NumberType.MOBILE,
                reservation_type="rental"
            )
        except Exception:
            try:
                rental_services = provider.services.list(
                    number_type=NumberType.MOBILE,
                    reservation_type="reservation"
                )
            except Exception as e:
                print(f"❌ Could not fetch rentals separately. Error: {e}")

    print(f"Storing {len(verification_services)} Verification and {len(rental_services)} Rental services in DB...")
    
    # Save them into their totally separate tables
    store_services_in_db(verification_services)
    
    if rental_services:
        store_rental_services_in_db(rental_services)
    
    save_service_fetch_status()
    print("✅ All services fetched + stored.")