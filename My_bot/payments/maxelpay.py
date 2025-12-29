import os
import time
import hmac
import hashlib
import httpx

MAXELPAY_API_KEY = os.getenv("MAXELPAY_API_KEY", "").strip()
MAXELPAY_API_SECRET = os.getenv("MAXELPAY_API_SECRET", "").strip()
MAXELPAY_BASE_URL = "https://api.maxelpay.com/v1/stg/merchant/order/checkout"  # change only if docs say sandbox URL

if not MAXELPAY_API_KEY or not MAXELPAY_API_SECRET:
    raise RuntimeError("MaxelPay API credentials not set")


def _sign_payload(payload: dict) -> str:
    """
    Create HMAC SHA256 signature from payload
    """
    payload_str = "&".join(f"{k}={payload[k]}" for k in sorted(payload))
    return hmac.new(
        MAXELPAY_API_SECRET.encode(),
        payload_str.encode(),
        hashlib.sha256,
    ).hexdigest()


async def create_maxelpay_checkout(
    *,
    order_id: str,
    amount_usd: float,
    user_name: str,
    user_email: str,
) -> str:

    url = f"https://api.maxelpay.com/v1/{MAXELPAY_ENV}/merchant/order/checkout"

    payload = {
        "orderID": order_id,
        "amount": float(f"{amount_usd:.2f}"),
        "currency": "USD",
        "timestamp": int(time.time()),
        "userName": user_name[:60],
        "userEmail": user_email,
        "siteName": "My TG Bot",
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
        r = await client.post(url, json=payload, headers=headers)

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
