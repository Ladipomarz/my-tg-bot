# My_bot/payments/maxelpay.py

import os
import time
import httpx

MAXELPAY_API_KEY = os.getenv("MAXELPAY_API_KEY", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")

API_BASE = "https://api.maxelpay.com/v1"  # sandbox/production is same endpoint


async def create_maxelpay_checkout(
    *,
    order_id: str,
    amount_usd: float,
    user_id: int,
    user_name: str = "Telegram User",
):
    if not MAXELPAY_API_KEY:
        raise RuntimeError("MAXELPAY_API_KEY not set")

    if not PUBLIC_BASE_URL:
        raise RuntimeError("PUBLIC_BASE_URL not set")

    payload = {
        "orderID": order_id,
        "amount": round(float(amount_usd), 2),
        "currency": "USD",
        "timestamp": int(time.time()),
        "userName": user_name[:60],
        # auto-generated email (no user input needed)
        "userEmail": f"tg_{user_id}@example.local",
        "siteName": "Telegram Bot Test",
        "websiteUrl": PUBLIC_BASE_URL,
        "redirectUrl": f"{PUBLIC_BASE_URL}/maxelpay/success",
        "cancelUrl": f"{PUBLIC_BASE_URL}/maxelpay/cancel",
        "webhookUrl": f"{PUBLIC_BASE_URL}/webhooks/maxelpay",
    }

    headers = {
        "Authorization": f"Bearer {MAXELPAY_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{API_BASE}/payment/create",
            json=payload,
            headers=headers,
        )

    if r.status_code >= 400:
        raise RuntimeError(f"MaxelPay {r.status_code}: {r.text}")

    data = r.json()

    # defensive check
    if "payment_url" not in data:
        raise RuntimeError(f"Unexpected MaxelPay response: {data}")

    return data["payment_url"]
