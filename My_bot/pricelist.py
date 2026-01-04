# My_bot/pricelist.py

# Service pricing (USD)
PRICES = {
    "msn": 1.00,
}

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
