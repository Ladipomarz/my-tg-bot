# My_bot/payments/nowpayments.py
import os
import httpx

NOWPAYMENTS_API_KEY = os.getenv("NOWPAYMENTS_API_KEY", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip()

API_BASE = "https://api.nowpayments.io/v1"


async def create_invoice(*, order_code: str, description: str, amount_usd: float) -> tuple[str, str]:
    if not NOWPAYMENTS_API_KEY:
        raise RuntimeError("NOWPAYMENTS_API_KEY not set")
    if not PUBLIC_BASE_URL:
        raise RuntimeError("PUBLIC_BASE_URL not set (must be your public https URL)")

    base = PUBLIC_BASE_URL.rstrip("/")

    payload = {
        "price_amount": float(f"{amount_usd:.2f}"),
        "price_currency": "usd",
        "order_id": order_code,
        "order_description": description,
        "ipn_callback_url": f"{base}/webhooks/nowpayments",
        "success_url": base,
        "cancel_url": base,

        # ✅ make checkout behave like "user pays fee"
        "is_fee_paid_by_user": True,
    }

    headers = {"x-api-key": NOWPAYMENTS_API_KEY, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.post(f"{API_BASE}/invoice", json=payload, headers=headers)

    # Helpful logs (Railway logs)
    print("NOWPAYMENTS payload:", payload)
    print("NOWPAYMENTS response:", r.status_code, r.text)

    if r.status_code >= 400:
        raise RuntimeError(f"NOWPayments {r.status_code}: {r.text}")

    data = r.json()

    if "invoice_url" not in data or "id" not in data:
        raise RuntimeError(f"NOWPayments response missing fields: {data}")

    return str(data["id"]), data["invoice_url"]


async def get_min_amount(*, pay_currency: str, price_currency: str = "usd") -> dict:
    """
    Returns NOWPayments minimum in the selected price_currency (usd).
    We'll use this to decide when BTC should be shown.
    """
    if not NOWPAYMENTS_API_KEY:
        raise RuntimeError("NOWPAYMENTS_API_KEY not set")

    headers = {"x-api-key": NOWPAYMENTS_API_KEY}
    params = {"pay_currency": pay_currency.lower(), "price_currency": price_currency.lower()}

    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.get(f"{API_BASE}/min-amount", params=params, headers=headers)

    print("NOWPAYMENTS min-amount:", pay_currency, r.status_code, r.text)

    if r.status_code >= 400:
        raise RuntimeError(f"NOWPayments min-amount {r.status_code}: {r.text}")

    return r.json()
