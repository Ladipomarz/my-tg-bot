# My_bot/pricelist.py

PRICES = {
    "ssn": 8.00,
}

DEFAULT_PRICE = 8.00


def get_price(service_code: str) -> float:
    return float(PRICES.get(service_code, DEFAULT_PRICE))
