# My_bot/pricelist.py

# Service pricing (USD)
PRICES = {
    "msn": 1.00,
}


# OTP verification pricing (USD)
# - "General Service" (unlisted / universal): $1.80 random, $2.70 specific state
# - All other listed services:              $3.00 random, $4.00 specific state
OTP_PRICES_USD = {
    "general_random": 1.80,
    "general_specific": 2.70,
    "standard_random": 3.00,
    "standard_specific": 4.00,
}

def get_otp_price_usd(*, is_general_service: bool, specific_state: bool) -> float:
    key = (
        "general_specific" if is_general_service and specific_state else
        "general_random" if is_general_service else
        "standard_specific" if specific_state else
        "standard_random"
    )
    return float(OTP_PRICES_USD[key])

ESIM_PRICES_USD = {
    "1m": 1.00,
    "3m": 31,   # set yours
    "1y": 100,  # set yours
}



def get_price(service_code: str) -> float:
    return float(PRICES.get(service_code))


# Plisio currency minimums (USD) — prevents 422 errors
PLISIO_MIN_USD = {
    "BTC": 1.00,
    "ETH": 2.00,
    "LTC": 1.00,
    "SOL": 1.00,
    "TRX": 1.00,
    "XMR": 2.00,
    "USDT_TRX": 5.10,
    "USDT_ETH": 10.00,
}


def get_plisio_min_usd(plisio_currency: str) -> float:
    return float(PLISIO_MIN_USD.get(plisio_currency.upper(), 1.00))


# Optional: map your UX coin keys -> Plisio codes (if you want a single source of truth)
COIN_MAP = {
    "btc": "BTC",
    "eth": "ETH",
    "ltc": "LTC",
    "sol": "SOL",
    "trx": "TRX",
    "xmr": "XMR",
    "usdttrc20": "USDT_TRX",
    "usdterc20": "USDT_ETH",
}



# 1. EXACT PRICES FOR STANDARD SERVICES (WhatsApp, Gmail, etc.)
RENTAL_BASE_PRICES = {
    "ONE_DAY": 3.50,       
    "THREE_DAY": 4.50,     
    "SEVEN_DAY": 5.60,    
    "FOURTEEN_DAY": 7.50, 
    "THIRTY_DAY": 9.00,  
    "ONE_MONTH": 9.00,  
    "TWO_MONTHS": 65.00,
    "THREE_MONTHS": 95.00,
    "SIX_MONTHS": 180.00,
    "NINE_MONTHS": 260.00,
    "ONE_YEAR": 340.00,
    "FOREVER": 999.00,
}

# 2. EXACT PRICES FOR UNIVERSAL / ALL SERVICES
UNIVERSAL_RENTAL_PRICES = {     
    "THREE_DAY": 10.33,     
    "SEVEN_DAY": 12.13,    
    "FOURTEEN_DAY": 14.50, 
    "THIRTY_DAY": 17.50,  
    "ONE_MONTH": 65.00, 
    "TWO_MONTHS": 65.00,
    "THREE_MONTHS": 95.00,
    "SIX_MONTHS": 180.00,
    "NINE_MONTHS": 260.00,
    "ONE_YEAR": 340.00,
    "FOREVER": 999.00,

}




# 1. EXACT PRICES FOR STANDARD SERVICES (WhatsApp, Gmail, etc.)
RENEWAL_BASE_PRICES = {
    "ONE_DAY": 3.20,       
    "THREE_DAY": 4.50,     
    "SEVEN_DAY": 5.60,    
    "FOURTEEN_DAY": 7.50, 
    "THIRTY_DAY": 9.00,  
    "ONE_MONTH": 65.00,  
    "TWO_MONTHS": 65.00,
    "THREE_MONTHS": 95.00,
    "SIX_MONTHS": 180.00,
    "NINE_MONTHS": 260.00,
    "ONE_YEAR": 340.00,
    "FOREVER": 999.00,
}

# 2. EXACT PRICES FOR UNIVERSAL / ALL SERVICES
RENEWAL_UNIVERSAL_PRICES = {     
    "THREE_DAY": 10.33,     
    "SEVEN_DAY": 12.13,    
    "FOURTEEN_DAY": 14.50, 
    "THIRTY_DAY": 17.50,  
    "ONE_MONTH": 65.00,  
    "TWO_MONTHS": 65.00,
    "THREE_MONTHS": 95.00,
    "SIX_MONTHS": 180.00,
    "NINE_MONTHS": 260.00,
    "ONE_YEAR": 340.00,
    "FOREVER": 999.00,

}


def get_rental_price_usd(service_name: str, duration_api: str, state: str) -> float:
    """Calculates the final rental price. STRICT MODE: No defaults."""
    
    # 1. Check if the user selected a Universal/AllServices line
    is_universal = service_name and any(keyword in service_name.lower() for keyword in ["universal", "general", "servicenotlisted", "not listed", "allservices"])
    
    # 2. STRICT LOOKUP (If the duration is missing, ABORT!)
    if is_universal:
        if duration_api not in UNIVERSAL_RENTAL_PRICES:
            raise ValueError(f"Pricing not found for Universal duration: {duration_api}")
        final_price = UNIVERSAL_RENTAL_PRICES[duration_api]
    else:
        if duration_api not in RENTAL_BASE_PRICES:
            raise ValueError(f"Pricing not found for Standard duration: {duration_api}")
        final_price = RENTAL_BASE_PRICES[duration_api]
            
    # 3. Add your flat premium if they requested a Specific State (e.g., + $2.00)
    if state and state.lower() != "random":
        final_price += 3.50  
        
    return round(final_price, 2)