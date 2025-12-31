import os
import asyncio
import logging

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

if not PUBLIC_BASE_URL:
    raise RuntimeError("PUBLIC_BASE_URL missing")
if not WEBHOOK_SECRET:
    raise RuntimeError("WEBHOOK_SECRET missing")

TELEGRAM_PATH = f"/webhook/{WEBHOOK_SECRET}"

app = FastAPI()

# ✅ Increase Telegram timeouts (fix ConnectTimeout / TimedOut)
tg_request = HTTPXRequest(
    connect_timeout=20.0,
    read_timeout=30.0,
    write_timeout=30.0,
    pool_timeout=30.0,
)

tg_app = ApplicationBuilder().token(BOT_TOKEN).request(tg_request).build()


async def on_error(update, context):
    logger.exception("Unhandled Telegram error", exc_info=context.error)


tg_app.add_error_handler(on_error)


async def _safe_send_message(chat_id: int, text: str):
    try:
        await tg_app.bot.send_message(chat_id=chat_id, text=text)
    except Exception:
        logger.exception("Telegram send_message failed")


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data:
        return

    data = (q.data or "").strip()
    user_id = q.from_user.id

    await q.answer()

    if data == "back_main":
        try:
            await q.edit_message_text("Back to main menu...")
        except Exception:
            pass
        await q.message.reply_text("Main menu:", reply_markup=get_main_menu())
        return

    # ✅ Gate ONLY before payment is detected
    if data.startswith("tool_"):
        pending = expire_pending_order_if_needed(user_id)

        if pending and pending.get("status") == "pending":
            pay_status = (pending.get("pay_status") or "").lower().strip()

            # block only if payment NOT detected yet
            if pay_status in {"pending", "", "new"}:
                await q.edit_message_text(
                    f"🕒 You have a pending order {pending['order_code']}.\nWhat do you want to do?",
                    reply_markup=get_pending_order_menu(),
                )
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
            await update.message.reply_text("❌ Something went wrong. Please start again.")
        return

    await handle_main_menu(update, context)


tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CallbackQueryHandler(callback_router))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))


async def _set_webhook_with_retry():
    """
    ✅ Do NOT crash startup if Telegram is slow.
    Retry a few times, then keep app running anyway.
    """
    webhook_url = f"{PUBLIC_BASE_URL}{TELEGRAM_PATH}"

    for attempt in range(1, 6):
        try:
            await tg_app.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
            logger.info("Telegram webhook set: %s", webhook_url)
            return
        except Exception as e:
            logger.exception("set_webhook failed (attempt %s/5): %s", attempt, e)
            await asyncio.sleep(2 * attempt)

    logger.error("Webhook NOT set after retries. App will keep running; it may recover on next deploy/restart.")


@app.on_event("startup")
async def on_startup():
    create_tables()

    await tg_app.initialize()
    await tg_app.start()

    # ✅ Don’t let this kill the app if Telegram times out
    await _set_webhook_with_retry()


@app.on_event("shutdown")
async def on_shutdown():
    await tg_app.stop()
    await tg_app.shutdown()


@app.post(TELEGRAM_PATH)
async def telegram_webhook(req: Request):
    payload = await req.json()
    update = Update.de_json(payload, tg_app.bot)
    await tg_app.process_update(update)
    return Response(status_code=200)


@app.post("/webhooks/plisio")
async def plisio_webhook(req: Request):
    ctype = (req.headers.get("content-type") or "").lower()

    try:
        if "multipart/form-data" in ctype or "application/x-www-form-urlencoded" in ctype:
            form = await req.form()  # requires python-multipart
            payload = dict(form)
        else:
            payload = await req.json()
    except Exception:
        body = await req.body()
        logger.warning("PLISIO WEBHOOK: parse failed content-type=%s body=%r", ctype, body[:500])
        return {"ok": True}

    p = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
    if not isinstance(p, dict):
        return {"ok": True}

    order_number = p.get("order_number") or p.get("orderNumber") or p.get("order_id") or p.get("orderId")
    txn_id = p.get("txn_id") or p.get("txid") or p.get("invoice") or p.get("invoice_id")
    status = (p.get("status") or p.get("state") or "").lower().strip()

    if not order_number:
        return {"ok": True}

    order = get_order_by_code(order_number) or {}
    user_id = order.get("user_id")
    current_pay_status = (order.get("pay_status") or "").lower().strip()

    paid_statuses = {"paid", "completed", "success", "confirmed", "finish", "finished"}
    expired_statuses = {"expired", "cancelled", "canceled", "failed", "error"}

    # ✅ Only treat "pending" as payment detected (not "new")
    detected_statuses = {"pending"}

    if status in detected_statuses:
        if current_pay_status not in {"detected", "paid"}:
            update_payment_status_by_order_code(order_number, pay_status="detected", pay_txn_id=txn_id)
            if user_id:
                asyncio.create_task(
                    _safe_send_message(
                        user_id,
                        f"✅ Payment detected for order {order_number}. Kindly wait while your order is being fulfilled.\n\nYou can return to Telegram now."
                    )
                )
        return {"ok": True}

    if status in paid_statuses:
        if current_pay_status != "paid":
            update_payment_status_by_order_code(order_number, pay_status="paid", pay_txn_id=txn_id)
        return {"ok": True}

    if status in expired_statuses:
        update_payment_status_by_order_code(order_number, pay_status="expired", pay_txn_id=txn_id)
        return {"ok": True}

    update_payment_status_by_order_code(order_number, pay_status=status or "pending", pay_txn_id=txn_id)
    return {"ok": True}


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/webhooks/plisio")
async def plisio_webhook_get():
    return {"ok": True}
