import os
import httpx
import logging

logger = logging.getLogger(__name__)

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

    logger.info(f"PAYMENT REQUEST: Currency: {crypto_currency}, Amount: ${amount_usd}, Order: {order_number}")

    params = {
        "api_key": PLISIO_API_KEY,
        "order_number": order_number,
        "order_name": order_name,
        "source_amount": f"{amount_usd:.2f}",
        "source_currency": "USD",
        "currency": crypto_currency,
        "allowed_psys_cids": crypto_currency,
        "allow_renew": 0,
        "callback_url": callback_url,
        "success_url": success_url,
        "fail_url": fail_url,
        "email_required": 0,
        "required_email": 0,
        "email": "",
        "return_existing": 0 
    }

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{PLISIO_BASE_URL}/invoices/new", params=params)

    # 🚨 THE FIX: Safe error messages that hide the provider's name
    if r.status_code != 200:
        logger.error(f"Plisio {r.status_code}: {r.text}") # You see this
        raise RuntimeError("Error In Making payment. Please try again later. Or Contact Support") # User sees this

    data = r.json()

    if data.get("status") != "success":
        logger.error(f"Plisio error: {data}")
        raise RuntimeError("Error In Making payment. Please try again later. Or Contact Support") # User sees this

    d = data.get("data") or {}

    invoice_url = d.get("invoice_url")
    txn_id = d.get("txn_id")
    invoice_total_sum = d.get("invoice_total_sum")

    if not invoice_url or not txn_id:
        logger.error(f"Missing invoice_url/txn_id in response: {data}")
        raise RuntimeError("Error In Making payment. Please try again later. Or Contact Support") # User sees this

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
        r = await client.get(f"{PLISIO_BASE_URL}/invoices/{txn_id}", params=params)

    if r.status_code != 200:
        logger.warning(f"PLISIO INVOICE DETAILS non-200: {r.status_code} {r.text}")
        return {}

    data = r.json()

    if data.get("status") != "success":
        return {}

    return data.get("data") or {}
