import os
import httpx

PLISIO_API_KEY = os.getenv("PLISIO_API_KEY", "").strip()
PLISIO_BASE_URL = "https://api.plisio.net/api/v1"

if not PLISIO_API_KEY:
    raise RuntimeError("PLISIO_API_KEY not set")


async def create_plisio_invoice(
    *,
    order_number: str,
    order_name: str,
    amount_usd: float,
    crypto_currency: str,      # BTC, SOL, XMR, USDT
    callback_url: str,
    success_url: str,
    fail_url: str,
) -> str:
    params = {
        "api_key": PLISIO_API_KEY,
        "order_number": order_number,
        "order_name": order_name,

        # ✅ fiat-based invoice: USD -> crypto conversion
        "source_amount": f"{amount_usd:.2f}",
        "source_currency": "USD",
        "currency": crypto_currency,

        "callback_url": callback_url,
        "success_url": success_url,
        "fail_url": fail_url,

        # try to disable email step
        "email_required": 0,
        "required_email": 0,
        "email": "",  # some checkouts skip if empty email is provided
    }

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{PLISIO_BASE_URL}/invoices/new", params=params)

    if r.status_code != 200:
        raise RuntimeError(f"Plisio {r.status_code}: {r.text}")

    data = r.json()
    print("PLISIO CREATE INVOICE RESPONSE:", data)

    if data.get("status") != "success":
        raise RuntimeError(f"Plisio error: {data}")

    invoice_url = (data.get("data") or {}).get("invoice_url")
    if not invoice_url:
        raise RuntimeError(f"No invoice_url in response: {data}")

    return invoice_url
