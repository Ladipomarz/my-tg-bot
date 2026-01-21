from textverified import TextVerified, NumberType, ReservationType
import os

from utils.db import (
    create_service_fetch_status_table,
    has_services_been_fetched,
    store_services_in_db,
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

    print("Fetching services...")
    services = provider.services.list(
        number_type=NumberType.MOBILE,
        reservation_type=ReservationType.VERIFICATION,
    )

    print(f"Storing {len(services)} services in the database...")
    store_services_in_db(services)
    save_service_fetch_status()
    print("✅ Services fetched + stored.")
