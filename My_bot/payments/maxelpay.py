import os
import time
import httpx

# ===== ENVIRONMENT VARIABLES =====
MAXELPAY_API_KEY = os.getenv("MAXELPAY_API_KEY", "").strip()
MAXELPAY_API_SECRET = os.getenv("MAXELPAY_API_SECRET", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")

if not MAXELPAY_API_KEY or not MAXELPAY_API_SECRET:
    raise RuntimeError("MAXELPAY_API_KEY or MAXELPAY_API_SECRET not set")

if not PUBLIC_BASE_URL:
    raise RuntimeError("PUBLIC_BASE_URL not set")

# ===== SANDBOX ENDPOINT =====
MAXELPAY_CHECKOUT_URL = "https://api.maxelpay.com/v1/stg/merchant/order/checkout"


async def create_maxelpay_checkout(
    *,
    order_id: str,
    amount_usd: float,
    user_name: str,
    user_email: str,
) -> str:
    """
    Creates a MaxelPay checkout session and returns the checkout URL
    """

    payload = {
        "orderID": order_id,
        "amount": float(f"{amount_usd:.2f}"),
        "currency": "USD",
        "timestamp": int(time.time()),
        "userName": user_name[:60],
        "userEmail": user_email,
        "siteName": "My Telegram Bot",
        "websiteUrl": PUBLIC_BASE_URL,
        "redirectUrl": f"{PUBLIC_BASE_URL}/success",
        "cancelUrl": f"{PUBLIC_BASE_URL}/cancel",
        "webhookUrl": f"{PUBLIC_BASE_URL}/webhooks/maxelpay",
    }

    headers = {
        "Content-Type": "application/json",
        "x-api-key": MAXELPAY_API_KEY,
        "x-api-secret": MAXELPAY_API_SECRET,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            MAXELPAY_CHECKOUT_URL,
            json=payload,
            headers=headers,
        )

    if r.status_code >= 400:
        raise RuntimeError(f"MaxelPay {r.status_code}: {r.text}")

    data = r.json()

    checkout_url = (
        data.get("checkoutUrl")
        or data.get("url")
        or (data.get("data") or {}).get("checkoutUrl")
    )

    if not checkout_url:
        raise RuntimeError(f"No checkout URL in response: {data}")

    return checkout_url
