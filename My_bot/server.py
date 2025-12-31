import os
import asyncio
import logging
import httpx
from fastapi import FastAPI, Request, Response
from utils.db import update_order_status


from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest

from config import BOT_TOKEN
from utils.db import (
    create_tables,
    update_payment_status_by_order_code,
    get_order_by_code,
    expire_pending_order_if_needed,
)
from menus.main_menu import get_main_menu
from menus.orders_menu import get_pending_order_menu

from handlers.start import start, handle_main_menu
from handlers.tools import tools_callback, handle_user_input
from handlers.orders import orders_callback
from handlers.payments import payments_callback

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()

PLISIO_API_KEY = os.getenv("PLISIO_API_KEY", "").strip()
PLISIO_BASE_URL = "https://api.plisio.net/api/v1"

if not PUBLIC_BASE_URL:
    raise RuntimeError("PUBLIC_BASE_URL missing")
if not WEBHOOK_SECRET:
    raise RuntimeError("WEBHOOK_SECRET missing")

TELEGRAM_PATH = f"/webhook/{WEBHOOK_SECRET}"

app = FastAPI()

# ✅ Telegram timeouts (Railway can be flaky)
tg_request = HTTPXRequest(
    connect_timeout=30.0,
    read_timeout=90.0,
    write_timeout=90.0,
    pool_timeout=90.0,
)

tg_app = ApplicationBuilder().token(BOT_TOKEN).request(tg_request).build()
TG_READY = False
TG_LOCK = asyncio.Lock()

async def ensure_telegram_ready():
    global TG_READY

    if TG_READY:
        return True

    async with TG_LOCK:
        if TG_READY:
            return True

        try:
            await tg_app.initialize()
            await tg_app.start()
            TG_READY = True
            logger.info("Telegram app is ready")
            return True
        except Exception as e:
            logger.exception("Telegram not ready yet: %s", e)
            return False



async def on_error(update, context):
    logger.exception("Unhandled Telegram error", exc_info=context.error)


tg_app.add_error_handler(on_error)


async def _safe_send_message(chat_id: int, text: str):
    # Retry a little because Telegram can timeout
    for attempt in range(1, 4):
        try:
            await tg_app.bot.send_message(chat_id=chat_id, text=text)
            return
        except Exception as e:
            logger.exception("Telegram send_message failed attempt %s/3: %s", attempt, e)
            await asyncio.sleep(1.5 * attempt)


def _to_float(x) -> float:
    try:
        return float(str(x).strip())
    except Exception:
        return 0.0


async def _fetch_plisio_invoice_details(txn_id: str) -> dict | None:
    """
    Fetch invoice details from Plisio, returns invoice dict or None.
    Endpoint seen in your logs:
      GET /invoices/{txn_id}?api_key=...
    """
    if not PLISIO_API_KEY or not txn_id:
        return None

    url = f"{PLISIO_BASE_URL}/invoices/{txn_id}"
    params = {"api_key": PLISIO_API_KEY}

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url, params=params)
        if r.status_code != 200:
            logger.warning("Plisio invoice details HTTP %s: %s", r.status_code, r.text[:300])
            return None

        data = r.json()
        if data.get("status") != "success":
            logger.warning("Plisio invoice details not success: %s", str(data)[:300])
            return None

        inv = (data.get("data") or {}).get("invoice") or {}
        return inv if isinstance(inv, dict) else None
    except Exception:
        logger.exception("Failed to fetch Plisio invoice details")
        return None


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data:
        return

    data = (q.data or "").strip()
    user_id = q.from_user.id

    # ✅ don't let q.answer timeouts kill your handler
    # ✅ Never let Telegram slowness break callbacks
    try:
           await q.answer(cache_time=2)
    except Exception as e:
     logger.warning("q.answer() failed (ignored): %s", e)


    if data == "back_main":
        try:
            await q.edit_message_text("Back to main menu...")
        except Exception:
            pass
        try:
            await q.message.reply_text("Main menu:", reply_markup=get_main_menu())
        except Exception:
            pass
        return

    # ✅ Gate ONLY before payment is detected
    if data.startswith("tool_"):
        pending = expire_pending_order_if_needed(user_id)

        if pending and pending.get("status") == "pending":
            pay_status = (pending.get("pay_status") or "").lower().strip()

            # block only if payment NOT detected yet
            if pay_status in {"pending", "", "new"}:
                try:
                    await q.edit_message_text(
                        f"🕒 You have a pending order {pending['order_code']}.\nWhat do you want to do?",
                        reply_markup=get_pending_order_menu(),
                    )
                except Exception:
                    logger.exception("edit_message_text failed (ignored)")
                return

        return await tools_callback(update, context)

    if data == "cancel_ssn":
        return await tools_callback(update, context)

    if data.startswith("orders_"):
        return await orders_callback(update, context)

    if data.startswith("pay_"):
        return await payments_callback(update, context)

    logger.info("Unhandled callback data: %s", data)


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("ssn_step"):
        try:
            await handle_user_input(update, context)
        except Exception:
            logger.exception("SSN flow error")
            for key in ["ssn_step", "first_name", "last_name", "type", "dob", "info", "from_ssn"]:
                context.user_data.pop(key, None)
            try:
                await update.message.reply_text("❌ Something went wrong. Please start again.")
            except Exception:
                pass
        return

    await handle_main_menu(update, context)


tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CallbackQueryHandler(callback_router))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))


async def _set_webhook_with_retry():
    webhook_url = f"{PUBLIC_BASE_URL}{TELEGRAM_PATH}"

    for attempt in range(1, 6):
        try:
            await tg_app.bot.set_webhook(url=webhook_url, drop_pending_updates=False)
            logger.info("Telegram webhook set: %s", webhook_url)
            return
        except Exception as e:
            logger.exception("set_webhook failed (attempt %s/5): %s", attempt, e)
            await asyncio.sleep(2 * attempt)

    logger.error("Webhook NOT set after retries. App will keep running.")


@app.on_event("startup")
async def on_startup():
    create_tables()
    # FastAPI starts even if Telegram is down
    asyncio.create_task(_background_telegram_bootstrap())


async def _background_telegram_bootstrap():
    webhook_url = f"{PUBLIC_BASE_URL}{TELEGRAM_PATH}"
    while True:
        ok = await ensure_telegram_ready()
        if ok:
            try:
                await tg_app.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
                logger.info("Telegram webhook set: %s", webhook_url)
                return
            except Exception as e:
                logger.exception("set_webhook failed (will retry): %s", e)
        await asyncio.sleep(10)


@app.on_event("shutdown")
async def on_shutdown():
    try:
        await tg_app.stop()
    except Exception:
        pass
    try:
        await tg_app.shutdown()
    except Exception:
        pass


@app.post(TELEGRAM_PATH)
async def telegram_webhook(req: Request):
    payload = await req.json()
    update = Update.de_json(payload, tg_app.bot)
    await tg_app.process_update(update)
    return Response(status_code=200)


@app.post("/webhooks/plisio")
async def plisio_webhook(req: Request):
    """
    Rules:
    - Send user message ONLY once when payment is DETECTED
    - Do NOT send message on paid/confirmed
    - Use DB lock to prevent spam
    - Detect reliably even if webhook doesn't include received_amount:
      -> call invoice details API using txn_id
    """
    ctype = (req.headers.get("content-type") or "").lower()

    # 1) Parse webhook body (form or json)
    try:
        if "multipart/form-data" in ctype or "application/x-www-form-urlencoded" in ctype:
            # requires python-multipart installed
            form = await req.form()
            payload = dict(form)
        else:
            payload = await req.json()
    except Exception:
        body = await req.body()
        logger.warning("PLISIO WEBHOOK: parse failed content-type=%s body=%r", ctype, body[:500])
        return {"ok": True}

    # 2) Unwrap {data:{...}} if present
    p = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
    if not isinstance(p, dict):
        return {"ok": True}

    order_number = (
        p.get("order_number")
        or p.get("orderNumber")
        or p.get("order_id")
        or p.get("orderId")
    )
    txn_id = p.get("txn_id") or p.get("txid") or p.get("invoice") or p.get("invoice_id")
    status = (p.get("status") or p.get("state") or "").lower().strip()

    if not order_number:
        return {"ok": True}

    order = get_order_by_code(order_number) or {}
    chat_id = order.get("user_id")
    current_pay_status = (order.get("pay_status") or "").lower().strip()

    paid_statuses = {"paid", "completed", "success", "confirmed", "finish", "finished"}
    expired_statuses = {"expired", "cancelled", "canceled", "failed", "error"}

    # -----------------------------
    # DETECTION LOGIC (NO SPAM)
    # -----------------------------
    # Goal: detect payment as soon as ANY funds are received (works for SOL/BTC/USDT etc)
    detected_now = False

    # A) If webhook provides received_amount, use it
    received_amount = _to_float(p.get("received_amount"))
    if received_amount > 0:
        detected_now = True
    else:
        # B) Otherwise fetch invoice details and detect using multiple fields
        inv = None
        if isinstance(txn_id, str) and txn_id.strip():
            inv = await _fetch_plisio_invoice_details(txn_id.strip())

        if inv and isinstance(inv, dict):
            total = _to_float(inv.get("invoice_total_sum") or inv.get("amount") or inv.get("invoice_sum"))
            received = _to_float(inv.get("received_amount"))
            remaining = _to_float(inv.get("remaining_amount"))
            pending_amt = _to_float(inv.get("pending_amount"))

            # ✅ detected if ANY money has moved
            if received > 0:
                detected_now = True
            elif total > 0 and remaining >= 0 and remaining < total:
                detected_now = True
            elif total > 0 and pending_amt >= 0 and pending_amt < total:
                detected_now = True

    # 1) If detected -> update DB + send ONCE (locked by DB)
    if detected_now:
        if current_pay_status not in {"detected", "paid"}:
            update_payment_status_by_order_code(order_number, pay_status="detected", pay_txn_id=txn_id)
            update_order_status(order["id"], "processing")
    
            # Send Telegram message ONLY if Telegram is reachable
            if chat_id and await ensure_telegram_ready():
                asyncio.create_task(
                    _safe_send_message(
                        chat_id,
                        f"✅ Payment detected for order {order_number}. Kindly wait while your order is being fulfilled.\n\nYou can return to Telegram now."
                    )
                )
            else:
                logger.warning("Telegram not ready; detected message skipped for %s", order_number)

        # ✅ IMPORTANT: stop here so we don't overwrite pay_status below
        return {"ok": True}

    # 2) Paid/confirmed -> update DB ONLY (NO user message)
    if status in paid_statuses:
        if current_pay_status != "paid":
            update_payment_status_by_order_code(order_number, pay_status="paid", pay_txn_id=txn_id)
        return {"ok": True}

    # 3) Expired/failed
    if status in expired_statuses:
        update_payment_status_by_order_code(order_number, pay_status="expired", pay_txn_id=txn_id)
        return {"ok": True}
    
    if current_pay_status in {"detected", "paid"}:
     return {"ok": True}
    
    # 4) Otherwise store status (optional)
    update_payment_status_by_order_code(order_number, pay_status=status or "pending", pay_txn_id=txn_id)
    return {"ok": True}

@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/webhooks/plisio")
async def plisio_webhook_get():
    return {"ok": True}
