import os
import time
import hmac
import hashlib
import httpx

MAXELPAY_API_KEY = os.getenv("MAXELPAY_API_KEY", "").strip()
MAXELPAY_API_SECRET = os.getenv("MAXELPAY_API_SECRET", "").strip()
MAXELPAY_BASE_URL = "https://api.maxelpay.com"  # change only if docs say sandbox URL

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
    user_id: int,
    user_name: str,
) -> str:
    timestamp = int(time.time())

    payload = {
        "orderID": order_id,
        "amount": round(float(amount_usd), 2),
        "currency": "USD",
        "timestamp": timestamp,
        "userName": user_name[:60],
        "siteName": "Telegram Bot Test",
        "userEmail": f"user{user_id}@example.com",  # auto-filled
        "websiteUrl": "https://example.com",
        "redirectUrl": "https://example.com/success",
        "cancelUrl": "https://example.com/cancel",
        "webhookUrl": "https://example.com/webhook",
    }

    signature = _sign_payload(payload)

    headers = {
        "X-API-KEY": MAXELPAY_API_KEY,
        "X-SIGNATURE": signature,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            f"{MAXELPAY_BASE_URL}/api/create-payment",
            json=payload,
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()

    if "payment_url" not in data:
        raise RuntimeError(f"Unexpected MaxelPay response: {data}")

    return data["payment_url"]
