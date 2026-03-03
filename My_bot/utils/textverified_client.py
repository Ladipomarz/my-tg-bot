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
    Fetches the live rental price from TextVerified and adds an 85% profit markup.
    """
    client, reservations, wake_requests, sms, NumberType, ReservationCapability, RentalDuration = get_textverified_client()
    
    # 🛑 THE SDK X-RAY 🛑
    print(f"🕵️ CLIENT MODULES: {[m for m in dir(client) if not m.startswith('_')]}")
    print(f"🕵️ SERVICES METHODS: {[m for m in dir(client.services) if not m.startswith('_')]}")
    # 1. Handle the "Universal" alias safely
    if service_name and any(keyword in service_name.lower() for keyword in ["universal", "general", "not listed", "allservices"]):
        api_service_name = "allservices"
    else:
        api_service_name = service_name

    # 2. Does the user want a specific state?
    # The pricing API expects a boolean (True/False) for area_code requests, not the string!
    requests_specific_state = bool(state and state.lower() != "random")

    # 3. Build the exact query the SDK wants
    kwargs = {
        "service_name": api_service_name,
        "number_type": NumberType.MOBILE,
        "capability": ReservationCapability.SMS,
        "duration": getattr(RentalDuration, duration_api),
        "always_on": always_on,
        "is_renewable": is_renewable,
        "area_code": requests_specific_state
    }

    try:
        # 4. Ask the API for the live price!
        price_response = await asyncio.to_thread(client.services.rental_pricing, **kwargs)
        
        # 5. Extract the raw cost
        base_cost = getattr(price_response, "cost", None) or getattr(price_response, "price", None)
        
        if base_cost is None and isinstance(price_response, dict):
            base_cost = price_response.get("cost") or price_response.get("price")
            
        if not base_cost:
            raise ValueError(f"Could not extract cost from API. Raw Response: {price_response}")
            
        # 6. 💰 THE 85% PROFIT ENGINE
        final_price = float(base_cost) * 1.85
        logger.info(f"💵 PRICING ENGINE: Base Cost ${base_cost} -> User Price ${final_price:.2f}")
        
        return round(final_price, 2)
        
    except Exception as e:
        logger.error(f"💥 Failed to fetch live rental price: {e}")
        
        