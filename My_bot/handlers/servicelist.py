import os
from textverified import TextVerified, NumberType, ReservationType
from utils.db import (
    create_service_fetch_status_table,
    get_connection,
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
    
    verification_count = 0
    rental_count = 0
    
    # 1. SMART DB CHECKING: Count what we already have
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM services;")
                row = cur.fetchone()
                verification_count = row[0]
                try:
                    cur.execute("SELECT COUNT(*) FROM rental_services;")
                    row2 = cur.fetchone()
                    rental_count = row2[0]
                except Exception:
                    rental_count = 0
    except Exception as e:
        print(f"Database count check failed: {e}")


    # If both lists are full, skip everything    
    if verification_count > 0 and rental_count > 0:
        print(f"✅ Both One-Time ({verification_count}) and Rental ({rental_count}) services are already safely in DB. Skipping fetch.")
        return
    
    print("Fetching the Master Service List from TextVerified...")
    master_services = []
    
    try:
        master_services = provider.services.list(
        number_type=NumberType.MOBILE,
        reservation_type=ReservationType.VERIFICATION,
    )
        
    except Exception as e:
        print(f"❌ Failed to fetch Master Service List: {e}")    
    
    if master_services:
        # Save to One-Time Database if empty
        if verification_count == 0:
            print("Storing in One-Time services table...")
            store_services_in_db(master_services)
        else:
            print(f"✅ One-Time services already exist ({verification_count}).")
                
        # Save to Rental Database if empty (This automatically starts at ID 5000!)
        if rental_count == 0:
            print("Storing in isolated Rental services table...")
            store_rental_services_in_db(master_services)
        else:
            print(f"✅ Rental services already exist ({rental_count}).")       
        
    save_service_fetch_status()
    print("✅ Startup fetch routine completed.")