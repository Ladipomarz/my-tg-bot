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

# ✅ THE PYTHON HACK: FakeEnum dynamically tests different reservation types
class FakeEnum:
    def __init__(self, val):
        self._val = val
        
    @property
    def value(self):
        return self._val

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
                verification_count = row[0] if row else 0
                
                try:
                    cur.execute("SELECT COUNT(*) FROM rental_services;")
                    row2 = cur.fetchone()
                    rental_count = row2[0] if row2 else 0
                except Exception:
                    rental_count = 0
    except Exception as e:
        print(f"Database count check failed: {e}")

    # 2. FETCH ONE-TIME SERVICES
    if verification_count > 0:
        print(f"✅ Found {verification_count} One-Time services in DB. Skipping fetch.")
    else:
        print("Fetching One-Time Verification services...")
        try:
            verification_services = provider.services.list(
                number_type=NumberType.MOBILE,
                reservation_type=ReservationType.VERIFICATION,
            )
            store_services_in_db(verification_services)
        except Exception as e:
            print(f"❌ Failed to fetch One-Time services: {e}")

    # 3. FETCH RENTAL SERVICES WITH AUTO-GUESSER
    if rental_count > 0:
        print(f"✅ Found {rental_count} Rental services in DB. Skipping fetch.")
    else:
        print("Fetching Rental services...")
        
        possible_words = [
            "renewable_rental", 
            "rental", 
            "line_reservation", 
            "nonrenewable_rental", 
            "reservations",
            None
        ]
        
        rental_services = []
        for word in possible_words:
            print(f"Trying API word: '{word}'...")
            try:
                if word is None:
                    rental_services = provider.services.list(number_type=NumberType.MOBILE)
                else:
                    rental_services = provider.services.list(
                        number_type=NumberType.MOBILE,
                        reservation_type=FakeEnum(word)
                    )
                
                if rental_services:
                    print(f"🎉 JACKPOT! Successfully downloaded {len(rental_services)} Rental services using '{word}'.")
                    store_rental_services_in_db(rental_services)
                    break
                    
            except Exception:
                continue
                
        if not rental_services:
            print("❌ Exhausted all guesses. Could not fetch Rental services.")

    save_service_fetch_status()
    print("✅ Startup fetch routine completed.")