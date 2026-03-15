import httpx
import logging
from datetime import datetime, timedelta
from config import SMSA_API_KEY
# 🟢 Import our new DB function
from utils.db import save_global_services_to_db, get_last_updated_time

logger = logging.getLogger(__name__)

async def get_or_fetch_country_services(country_id: int):
    """
    The Check-then-Fetch Logic:
    1. Checks if data exists for this country using db.py.
    2. Checks if data is older than 24 hours.
    3. Fetches from API only if necessary.
    """
    needs_fetch = False
    
    # 🟢 Clean call to db.py (No SQL here!)
    last_update = get_last_updated_time(country_id)
    
    # LOGIC: If no data OR data is older than 24 hours
    if last_update is None:
        needs_fetch = True
    else:
        # Compare last update time with current time (24 hour window)
        if datetime.now() - last_update > timedelta(hours=24):
            needs_fetch = True

    if needs_fetch:
        logger.info(f"🔄 Data for Country {country_id} is missing or stale. Fetching fresh data...")
        return await fetch_and_save_global_services(country_id)
    else:
        logger.info(f"✅ Data for Country {country_id} is fresh (within 24h). Skipping API call.")
        return True

async def fetch_and_save_global_services(country_id: int):
    if not SMSA_API_KEY:
        logger.error("❌ SMSA_API_KEY is missing!")
        return False

    url = "https://www.smsactivate.com/api/sms.php"
    
    # We will try both common action names if the first one is empty
    actions_to_try = ["getPrices", "get_prices"]
    
    async with httpx.AsyncClient(timeout=20) as client:
        for action in actions_to_try:
            params = {
                "api_key": SMSA_API_KEY,
                "action": action,
                "country": country_id,
                "json": 1
            }
            
            try:
                resp = await client.get(url, params=params)
                logger.info(f"🔍 Testing {action} - Status: {resp.status_code}")
                
                data = resp.json()
                
                # If we got more than just {"success": true}, we found the data!
                if data.get("success") is True and len(data) > 1:
                    logger.info(f"✅ Data found using {action}")
                    # Process and save to DB
                    return await process_and_save_data(country_id, data)
                
            except Exception as e:
                logger.error(f"❌ Error during {action}: {e}")
                continue

    logger.warning(f"⚠️ Both actions returned empty for Country {country_id}. check balance/permissions.")
    return False

async def process_and_save_data(country_id, prices_data):
    # This is where your existing loop for cost_rub and stock lives
    # ... logic to save to global_services ...
    return True