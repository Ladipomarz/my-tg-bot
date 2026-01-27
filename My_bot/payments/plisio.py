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
    crypto_currency: str,      # BTC, ETH, LTC, SOL, TRX, XMR, USDT_TRX, USDT_ETH
    callback_url: str,
    success_url: str,
    fail_url: str,
) -> dict:
    """
    Creates a Plisio invoice and returns:
    { txn_id, invoice_url, invoice_total_sum }
    """

    print("PLISIO REQUEST:", {"currency": crypto_currency, "amount_usd": amount_usd, "order_number": order_number})

    params = {
        "api_key": PLISIO_API_KEY,

        "order_number": order_number,
        "order_name": order_name,

        # USD → crypto conversion
        "source_amount": f"{amount_usd:.2f}",
        "source_currency": "USD",

        # Force selected coin (best-effort)
        "currency": crypto_currency,
        "allowed_psys_cids": crypto_currency,
        "allow_renew": 0,
        "callback_url": callback_url,
        "success_url": success_url,
        "fail_url": fail_url,

        # Try to disable email page (best-effort)
        "email_required": 0,
        "required_email": 0,
        "email": "",
        
        "return_existing": 1,   # if order_number exists, return it instead of 422
        "expire_min": 16,        # OPTIONAL: invoice expires in 1 minute

        
    }

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{PLISIO_BASE_URL}/invoices/new", params=params)

    if r.status_code != 200:
        raise RuntimeError(f"Plisio {r.status_code}: {r.text}")

    data = r.json()
    print("PLISIO CREATE INVOICE RESPONSE:", data)

    if data.get("status") != "success":
        raise RuntimeError(f"Plisio error: {data}")

    d = data.get("data") or {}

    invoice_url = d.get("invoice_url")
    txn_id = d.get("txn_id")
    invoice_total_sum = d.get("invoice_total_sum")  # crypto amount string often

    if not invoice_url or not txn_id:
        raise RuntimeError(f"Missing invoice_url/txn_id in response: {data}")

    return {
        "invoice_url": invoice_url,
        "txn_id": txn_id,
        "invoice_total_sum": invoice_total_sum,
    }


async def get_plisio_invoice_details(txn_id: str) -> dict:
    """
    Fetch invoice details by txn_id.
    Goal: get payment address if Plisio returns it for your plan/settings.
    Returns raw 'data' dict (or {}).
    """
    params = {"api_key": PLISIO_API_KEY}

    async with httpx.AsyncClient(timeout=20) as client:
        # Plisio uses GET /invoices/{id}
        r = await client.get(f"{PLISIO_BASE_URL}/invoices/{txn_id}", params=params)

    if r.status_code != 200:
        # Don't hard-fail: just return empty, we can still show invoice_url
        print("PLISIO INVOICE DETAILS non-200:", r.status_code, r.text)
        return {}

    data = r.json()
    print("PLISIO INVOICE DETAILS RESPONSE:", data)

    if data.get("status") != "success":
        return {}

    return data.get("data") or {}
