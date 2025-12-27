import os
import httpx

NOWPAYMENTS_API_KEY = os.getenv("NOWPAYMENTS_API_KEY", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip()
API_BASE = "https://api.nowpayments.io/v1"


async def create_invoice(*, order_code: str, description: str, amount_usd: float, pay_currency: str | None = None) -> tuple[str, str]:
    if not NOWPAYMENTS_API_KEY:
        raise RuntimeError("NOWPAYMENTS_API_KEY not set")
    if not PUBLIC_BASE_URL:
        raise RuntimeError("PUBLIC_BASE_URL not set")

    base = PUBLIC_BASE_URL.rstrip("/")

    payload = {
        "price_amount": float(f"{amount_usd:.2f}"),
        "price_currency": "usd",
        "order_id": order_code,
        "order_description": description,
        "ipn_callback_url": f"{base}/webhooks/nowpayments",
        "success_url": base,
        "cancel_url": base,
        "is_fee_paid_by_user": True,
    }

    if pay_currency:
        payload["pay_currency"] = pay_currency.lower()

    headers = {"x-api-key": NOWPAYMENTS_API_KEY, "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.post(f"{API_BASE}/invoice", json=payload, headers=headers)

    print("NOWPAYMENTS payload:", payload)
    print("NOWPAYMENTS response:", r.status_code, r.text)

    if r.status_code >= 400:
        raise RuntimeError(f"NOWPayments {r.status_code}: {r.text}")

    data = r.json()
    return str(data["id"]), data["invoice_url"]
