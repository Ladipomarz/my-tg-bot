import httpx
import logging
from datetime import datetime, timedelta
from config import SMSA_API_KEY
from utils.db import save_global_services_to_db, get_connection
logger = logging.getLogger(__name__)


async def fetch_and_save_global_services(country_id: int):
    """
    1. Fetches the master name list (e.g., 'tg' -> 'Telegram').
    2. Fetches current prices and stock for the specific country.
    3. Calculates USD prices with profit and saves to the global_services table.
    """
    if not SMSA_API_KEY:
        logger.error("❌ SMSA_API_KEY is missing! Check your Railway Variables.")
        return False

    # 🟢 THE FIX: Replaced .org with smsactivate.com AND added &json=1
    names_url = "https://smsactivate.com/api/api.php?act=getServicesList"
    prices_url = f"https://smsactivate.com/stubs/handler_api.php?api_key={SMSA_API_KEY}&action=getPrices&country={country_id}&json=1"

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            # Fetch names and prices in parallel
            names_resp = await client.get(names_url)
            prices_resp = await client.get(prices_url)
            
        # 🛡️ SAFETY CHECK: Ensure we actually got JSON back
        try:
            service_names = names_resp.json().get("services", {})
            prices_data = prices_resp.json().get(str(country_id), {})
        except Exception as json_err:
            logger.error(f"❌ SMSA did not return valid JSON. Text: {prices_resp.text}")
            return False

        if not prices_data:
            logger.warning(f"⚠️ No services found for Country {country_id}")
            return False

        ready_to_save = []
        for code, info in prices_data.items():
            stock = int(info.get("count", 0))
            if stock <= 0:
                continue 

            cost_rub = float(info.get("cost", 0))
            
            # 💲 Calculation: (Rubles * 0.011) + $1.50 Profit
            price_usd = round((cost_rub * 0.011) + 1.50, 2)
            
            # Use the master name list to translate the shortcode
            name = service_names.get(code, code.upper())

            ready_to_save.append({
                'code': code,
                'name': name,
                'price': price_usd,
                'stock': stock
            })

        # Save to the database using the function in utils/db.py
        save_global_services_to_db(country_id, ready_to_save)
        logger.info(f"✅ Successfully saved {len(ready_to_save)} services for Country {country_id} to DB.")
        return True

    except Exception as e:
        logger.error(f"💥 SMSA Fetch Error: {e}")
        return False