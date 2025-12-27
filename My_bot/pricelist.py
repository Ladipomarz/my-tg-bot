# My_bot/pricelist.py

PRICES = {
    "ssn": 13.00,
}

DEFAULT_PRICE = 13.00


def get_price(service_code: str) -> float:
    return float(PRICES.get(service_code, DEFAULT_PRICE))
