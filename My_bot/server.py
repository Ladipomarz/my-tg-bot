import os
import json
import logging
from urllib.parse import parse_qs

from fastapi import FastAPI, Request, Response

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

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

if not PUBLIC_BASE_URL:
    raise RuntimeError("PUBLIC_BASE_URL missing")
if not WEBHOOK_SECRET:
    raise RuntimeError("WEBHOOK_SECRET missing")

TELEGRAM_PATH = f"/webhook/{WEBHOOK_SECRET}"

app = FastAPI()
tg_app = ApplicationBuilder().token(BOT_TOKEN).build()


async def on_error(update, context):
    logger.exception("Unhandled Telegram error", exc_info=context.error)


tg_app.add_error_handler(on_error)


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data:
        return

    data = (q.data or "").strip()
    user_id = q.from_user.id

    await q.answer()

    # back to main menu (inline)
    if data == "back_main":
        try:
            await q.edit_message_text("Back to main menu...")
        except Exception:
            pass
        await q.message.reply_text("Main menu:", reply_markup=get_main_menu())
        return

    # ✅ Gate tool_ inline buttons (pending check)
    if data.startswith("tool_"):
        pending = expire_pending_order_if_needed(user_id)
        if pending and pending.get("status") == "pending":
            await q.edit_message_text(
                f"🕒 You have a pending order {pending['order_code']}.\nWhat do you want to do?",
                reply_markup=get_pending_order_menu(),
            )
            return
        return await tools_callback(update, context)

    # allow cancel_ssn always
    if data == "cancel_ssn":
        return await tools_callback(update, context)

    # orders menu inline callbacks
    if data.startswith("orders_"):
        return await orders_callback(update, context)

    # payments menu inline callbacks
    if data.startswith("pay_"):
        return await payments_callback(update, context)

    logger.info("Unhandled callback data: %s", data)


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # If in SSN flow, handle it safely
    if context.user_data.get("ssn_step"):
        try:
            await handle_user_input(update, context)
        except Exception:
            logger.exception("SSN flow error")
            for key in ["ssn_step", "first_name", "last_name", "type", "dob", "info", "from_ssn"]:
                context.user_data.pop(key, None)
            await update.message.reply_text("❌ Something went wrong. Please start again.")
        return

    # static ReplyKeyboard main menu routing lives here
    await handle_main_menu(update, context)


# Telegram handlers
tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CallbackQueryHandler(callback_router))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))


@app.on_event("startup")
async def on_startup():
    create_tables()

    await tg_app.initialize()
    await tg_app.start()

    webhook_url = f"{PUBLIC_BASE_URL}{TELEGRAM_PATH}"
    await tg_app.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
    logger.info("Telegram webhook set: %s", webhook_url)


@app.on_event("shutdown")
async def on_shutdown():
    await tg_app.stop()
    await tg_app.shutdown()


@app.post(TELEGRAM_PATH)
async def telegram_webhook(req: Request):
    payload = await req.json()
    logger.info("TG UPDATE received: %s", payload.get("update_id"))
    update = Update.de_json(payload, tg_app.bot)
    await tg_app.process_update(update)
    return Response(status_code=200)


def _parse_plisio_body(body: bytes) -> dict:
    """
    Parse Plisio webhook body WITHOUT req.form() (no python-multipart needed).
    Supports:
      - JSON
      - application/x-www-form-urlencoded (key=value&...)
    """
    if not body or body.strip() == b"":
        return {}

    # Try JSON first
    try:
        return json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        pass

    # Fallback: parse querystring-like body
    decoded = body.decode("utf-8", errors="replace")
    qs = parse_qs(decoded)
    return {k: (v[0] if len(v) == 1 else v) for k, v in qs.items()}


@app.post("/webhooks/plisio")
async def plisio_webhook(req: Request):
    body = await req.body()

    # Empty body: ignore
    if not body or body.strip() == b"":
        logger.warning("PLISIO WEBHOOK: empty body, headers=%s", dict(req.headers))
        return {"ok": True}

    payload = _parse_plisio_body(body)
    logger.info("PLISIO WEBHOOK parsed: %s", payload)

    # Some accounts send payload in {data:{...}} others send flat
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

    # Load order (for user_id and to avoid message spam)
    order = get_order_by_code(order_number) or {}
    user_id = order.get("user_id")
    current_pay_status = (order.get("pay_status") or "").lower().strip()

    # Status groups
    paid = {"paid", "completed", "success", "confirmed", "finish", "finished"}
    expired = {"expired", "cancelled", "canceled", "failed", "error"}
    detected = {"pending", "new"}  # payment seen but not confirmed

    # 1) Payment detected (send ONCE)
    if status in detected:
        if current_pay_status not in {"detected", "paid"}:
            update_payment_status_by_order_code(order_number, pay_status="detected", pay_txn_id=txn_id)
            if user_id:
                try:
                    await tg_app.bot.send_message(
                        chat_id=user_id,
                        text=f"✅ Payment detected for order {order_number}. Kindly wait while your order is being fulfilled.",
                    )
                except Exception:
                    logger.exception("Failed to notify user for detected payment")
        return {"ok": True}

    # 2) Paid/confirmed (final)
    if status in paid:
        if current_pay_status != "paid":
            update_payment_status_by_order_code(order_number, pay_status="paid", pay_txn_id=txn_id)
            if user_id:
                try:
                    await tg_app.bot.send_message(
                        chat_id=user_id,
                        text=f"✅ Payment confirmed for order {order_number}.",
                    )
                except Exception:
                    logger.exception("Failed to notify user for paid order")
        return {"ok": True}

    # 3) Expired/failed
    if status in expired:
        update_payment_status_by_order_code(order_number, pay_status="expired", pay_txn_id=txn_id)
        return {"ok": True}

    # 4) Anything else: store as-is (don’t crash)
    update_payment_status_by_order_code(order_number, pay_status=status or "pending", pay_txn_id=txn_id)
    return {"ok": True}


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/webhooks/plisio")
async def plisio_webhook_get():
    return {"ok": True}
