import os
import httpx

NOWPAYMENTS_API_KEY = os.getenv("NOWPAYMENTS_API_KEY")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL")  # must be your public https railway URL

API_BASE = "https://api.nowpayments.io/v1"


async def create_invoice(*, order_code: str, description: str, amount_usd: float) -> tuple[str, str]:
    if not NOWPAYMENTS_API_KEY:
        raise RuntimeError("NOWPAYMENTS_API_KEY not set")
    if not PUBLIC_BASE_URL:
        raise RuntimeError("PUBLIC_BASE_URL not set (example: https://your-app.up.railway.app)")

    base = PUBLIC_BASE_URL.rstrip("/")

    payload = {
        "price_amount": float(f"{amount_usd:.2f}"),
        "price_currency": "usd",
        "order_id": order_code,
        "order_description": description,

        # IPN (webhook) callback:
        "ipn_callback_url": f"{base}/webhooks/nowpayments",

        # These are important for /v1/invoice (missing them often causes 400):
        "success_url": base,
        "cancel_url": base,
    }

    headers = {
        "x-api-key": NOWPAYMENTS_API_KEY,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.post(f"{API_BASE}/invoice", json=payload, headers=headers)

        # Show the real NOWPayments error in logs (super helpful)
        if r.status_code >= 400:
            raise RuntimeError(f"NOWPayments error {r.status_code}: {r.text}")

        data = r.json()

    return str(data["id"]), data["invoice_url"]
