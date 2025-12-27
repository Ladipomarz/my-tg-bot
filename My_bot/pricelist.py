# My_bot/pricelist.py

PRICES = {
    "ssn": 7.00,
}

DEFAULT_PRICE = 7.00


def get_price(service_code: str) -> float:
    return float(PRICES.get(service_code, DEFAULT_PRICE))
