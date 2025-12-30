import os
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
logger = logging.getLogger(__name__)

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

    # back to main menu
    if data == "back_main":
        await q.edit_message_text("Back to main menu...")
        await q.message.reply_text("Main menu:", reply_markup=get_main_menu())
        return

    # ✅ PENDING ORDER GATE FOR TOOLS (restored)
    if data.startswith("tool_"):
        pending = expire_pending_order_if_needed(user_id)
        if pending and pending.get("status") == "pending":
            await q.edit_message_text(
                f"🕒 You have a pending order {pending['order_code']}.\nWhat do you want to do?",
                reply_markup=get_pending_order_menu(),
            )
            return
        return await tools_callback(update, context)

    # cancel_ssn should ALWAYS work even if pending
    if data == "cancel_ssn":
        return await tools_callback(update, context)

    # orders menu callbacks
    if data.startswith("orders_"):
        return await orders_callback(update, context)

    # payments callbacks
    if data.startswith("pay_"):
        return await payments_callback(update, context)

    logger.info("Unhandled callback data: %s", data)


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # SSN flow
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


@app.post("/webhooks/plisio")
async def plisio_webhook(req: Request):
    payload = await req.json()
    logger.info("PLISIO WEBHOOK: %s", payload)

    p = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload

    order_number = (
        p.get("order_number") or p.get("orderID") or p.get("order_id") or p.get("order") or p.get("orderNumber")
    )
    txn_id = p.get("txn_id") or p.get("txid") or p.get("invoice") or p.get("invoice_id")
    status = (p.get("status") or p.get("state") or "").lower().strip()

    if not order_number:
        return {"ok": True}

    paid = {"paid", "completed", "success", "confirmed", "finish", "finished"}
    expired = {"expired", "cancelled", "canceled", "failed", "error"}

    if status in paid:
        update_payment_status_by_order_code(order_number, pay_status="paid", pay_txn_id=txn_id)

        order = get_order_by_code(order_number)
        if order and order.get("user_id"):
            await tg_app.bot.send_message(
                chat_id=order["user_id"],
                text=f"✅ Payment confirmed for order {order_number}.",
            )

    elif status in expired:
        update_payment_status_by_order_code(order_number, pay_status="expired", pay_txn_id=txn_id)
    else:
        update_payment_status_by_order_code(order_number, pay_status=status or "pending", pay_txn_id=txn_id)

    return {"ok": True}


@app.get("/health")
async def health():
    return {"ok": True}
