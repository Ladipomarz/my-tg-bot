import os
import httpx

NOWPAYMENTS_API_KEY = os.getenv("NOWPAYMENTS_API_KEY")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL")

API_BASE = "https://api.nowpayments.io/v1"


async def create_invoice(*, order_code: str, description: str, amount_usd: float) -> tuple[str, str]:
    if not NOWPAYMENTS_API_KEY:
        raise RuntimeError("NOWPAYMENTS_API_KEY not set")
    if not PUBLIC_BASE_URL:
        raise RuntimeError("PUBLIC_BASE_URL not set")

    payload = {
        "price_amount": amount_usd,
        "price_currency": "usd",
        "order_id": order_code,
        "order_description": description,
        "ipn_callback_url": f"{PUBLIC_BASE_URL.rstrip('/')}/webhooks/nowpayments",
        "is_fixed_rate": True,
    }

    headers = {"x-api-key": NOWPAYMENTS_API_KEY, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.post(f"{API_BASE}/invoice", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()

    return str(data["id"]), data["invoice_url"]
