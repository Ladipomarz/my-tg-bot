# utils/textverified_client.py
from textverified import (
    TextVerified,
    reservations,
    wake_requests,
    sms,
    NumberType,
    ReservationCapability,
    RentalDuration,
)
import os
import asyncio
import logging

logger = logging.getLogger(__name__)

def get_textverified_client():
    API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
    API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")
    
    # Create the TextVerified client
    client = TextVerified(api_key=API_KEY, api_username=API_USERNAME)
    
    # Return both the client and other components for convenience
    return client, reservations, wake_requests, sms, NumberType, ReservationCapability, RentalDuration



async def get_dynamic_rental_price(service_name: str, state: str, duration_api: str, always_on: bool, is_renewable: bool) -> float:
    """
    Bypasses the buggy Python wrapper and queries the V2 TextVerified Pricing API directly.
    """
    client, reservations, wake_requests, sms, NumberType, ReservationCapability, RentalDuration = get_textverified_client()
    
    # 1. Handle Universal Override
    if service_name and any(keyword in service_name.lower() for keyword in ["universal", "general", "not listed", "allservices"]):
        api_service_name = "allservices"
    else:
        api_service_name = service_name

    # 2. Map your internal duration keys to the exact V2 Strings they require
    v2_duration_map = {
        "ONE_DAY": "1 Day",
        "THREE_DAY": "3 Days",
        "SEVEN_DAY": "1 Week",
        "FOURTEEN_DAY": "2 Weeks",
        "THIRTY_DAY": "1 Month"
    }
    exact_duration = v2_duration_map.get(duration_api, "1 Day")

    # 3. Build the exact JSON body for POST /api/pub/v2/pricing/rentals
    payload = {
        "service_name": api_service_name,
        "number_type": "Mobile",
        "reservation_type": "SMS",
        "duration": exact_duration,
        "always_on": always_on,
        "is_renewable": is_renewable
    }

    # 4. Attach Area Code requests if they picked a specific state
    if state and state.lower() != "random":
        from handlers.otp_handler import _area_codes_for_state
        acs = _area_codes_for_state(state)
        if acs:
            payload["area_code_select_option"] = acs[:15]

    try:
        # 5. The Magic Trick: Use the client's pre-authenticated session to hit the raw URL!
        url = f"{client.base_url}/api/pub/v2/pricing/rentals"
        
        # We push the POST request directly to the server
        response = await asyncio.to_thread(client.session.post, url, json=payload)
        
        # If the API rejects our payload, we print exactly why
        if response.status_code != 200:
            logger.error(f"💥 API REJECTED PRICING: {response.text}")
            raise ValueError(f"TextVerified Pricing API Error: {response.text}")

        # 6. Extract the real-time cost directly from the raw JSON response
        data = response.json()
        print(f"🕵️ LIVE TEXTVERIFIED QUOTE: {data}")
        
        base_cost = data.get("cost") or data.get("price")
        
        if not base_cost:
            raise ValueError("No 'cost' found in API response")

        # 7. 💰 APPLY YOUR 85% PROFIT MARKUP
        final_price = float(base_cost) * 1.85
        
        return round(final_price, 2)

    except Exception as e:
        logger.error(f"💥 Live Pricing Engine Failed: {e}")
        raise e