import os
import asyncio
import logging
import httpx
import io
import datetime

from fastapi import FastAPI, Request, Response

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest
from handlers.admin import admin_command, admin_callback
from menus.admin_menu import get_admin_menu  # optional if you want to show it elsewhere


from config import BOT_TOKEN

from utils.db import (
    create_tables,
    update_payment_status_by_order_code,
    get_order_by_code,
    expire_pending_order_if_needed,
    update_order_status,
    save_delivery_file_by_code,
    mark_order_delivered,
)

from utils.auto_delete import safe_delete_user_message

from menus.main_menu import get_main_menu
from menus.orders_menu import get_pending_order_menu

from handlers.start import start, handle_main_menu
from handlers.orders import orders_callback, debug_last_order
from handlers.payments import payments_callback
from handlers.tools import tools_callback, handle_user_input, handle_esim_email_input


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()

PLISIO_API_KEY = os.getenv("PLISIO_API_KEY", "").strip()
PLISIO_BASE_URL = "https://api.plisio.net/api/v1"

# Admin IDs (comma-separated Telegram user IDs)
# Example: ADMIN_IDS="12345678,987654321"
ADMIN_IDS = {
    int(x.strip())
    for x in (os.getenv("ADMIN_IDS", "")).split(",")
    if x.strip().isdigit()
}

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
            logger.exception(
                "Telegram send_message failed attempt %s/3: %s", attempt, e
            )
            await asyncio.sleep(1.5 * attempt)


async def _notify_admin_new_paid_order(order: dict):
    """
    Send admin: 🟡 New paid order ... [Deliver (.txt)]
    Triggered when payment transitions into detected for the first time.
    """
    if not ADMIN_IDS:
        logger.warning("ADMIN_IDS not set; admin notifications skipped")
        return

    order_code = (order.get("order_code") or "").strip()
    desc = (order.get("description") or "").strip() or "Service"
    user_id = order.get("user_id")

    text = (
        "🟡 New paid order\n"
        f"Order: {order_code}\n"
        f"User: {user_id}\n"
        f"Item: {desc}\n\n"
        "Tap Deliver (.txt) then reply with the delivery text."
    )

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Deliver (.txt)", callback_data=f"admin_deliver:{order_code}"
                )
            ]
        ]
    )

    for admin_id in ADMIN_IDS:
        try:
            await tg_app.bot.send_message(chat_id=admin_id, text=text, reply_markup=kb)
        except Exception:
            logger.exception(
                "Failed to notify admin %s for order %s", admin_id, order_code
            )


async def _delete_message_later(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data.get("chat_id")
    message_id = job.data.get("message_id")
    if not chat_id or not message_id:
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        # ignore delete errors
        pass


def _to_float(x) -> float:
    try:
        return float(str(x).strip())
    except Exception:
        return 0.0


async def _fetch_plisio_invoice_details(txn_id: str) -> dict | None:
    """
    Fetch invoice details from Plisio, returns invoice dict or None.
    Endpoint:
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
            logger.warning(
                "Plisio invoice details HTTP %s: %s", r.status_code, r.text[:300]
            )
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


# ✅ eSIM: delayed message (3 minutes after payment detected)
async def send_esim_processing_notice(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data["chat_id"]

    msg = (
        "Usually Esims take 24 hours to be processed but we will make sure to make this faster "
        "do not reach out to support until 24 hours is elapsed and package not received"
    )
    await context.bot.send_message(chat_id=chat_id, text=msg)


# ------------------------------
# CALLBACK ROUTER (INLINE BUTTONS)
# ------------------------------
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data:
        return

    data = (q.data or "").strip()
    user_id = q.from_user.id

    # Never let Telegram slowness break callbacks
    try:
        await q.answer(cache_time=2)
    except Exception as e:
        logger.warning("q.answer() failed (ignored): %s", e)

    logger.info("callback_router got data=%r", data)

    # Back to main
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

    # ✅ Admin callbacks (deliver flow)
    if data.startswith("admin_deliver:"):
        if user_id not in ADMIN_IDS:
            try:
                await q.edit_message_text("❌ Not authorized.")
            except Exception:
                pass
            return

        order_code = data.split(":", 1)[1].strip()
        order = get_order_by_code(order_code)
        if not order:
            try:
                await q.edit_message_text("❌ Order not found.")
            except Exception:
                pass
            return

        pay_status = (order.get("pay_status") or "").lower().strip()
        delivery_status = (order.get("delivery_status") or "").lower().strip()

        # We treat detected as good enough to fulfill (per your request)
        if pay_status not in {"detected", "paid"}:
            try:
                await q.edit_message_text(
                    f"❌ Order {order_code} is not paid/detected yet."
                )
            except Exception:
                pass
            return

        if delivery_status == "delivered":
            try:
                await q.edit_message_text(
                    f"✅ Order {order_code} is already delivered."
                )
            except Exception:
                pass
            return
        if (
            data == "admin_menu"
            or data.startswith("admin_paid:")
            or data.startswith("admin_delivered:")
        ):
            return await admin_callback(update, context, ADMIN_IDS)

        # set admin pending state
        context.user_data["admin_deliver_waiting"] = True
        context.user_data["admin_deliver_order_code"] = order_code

        try:
            await q.edit_message_text(
                f"✅ Deliver mode for {order_code}\n\n"
                "Now reply with the delivery text (the content that should go into service.txt)."
            )
        except Exception:
            pass
        return

    # Tools / SSN / eSIM callbacks
    is_tools_related = (
        data.startswith("tool_")
        or data == "esim_services"
        or data.startswith("esim_duration:")
        or data in {"ssn_back", "cancel_ssn"}
    )
    if is_tools_related:
        # Gate ONLY before payment is detected
        pending = expire_pending_order_if_needed(user_id)
        if pending and pending.get("status") == "pending":
            pay_status = (pending.get("pay_status") or "").lower().strip()
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

    # Orders callbacks
    if (
        data.startswith("orders_")
        or data.startswith("order_file:")
        or data.startswith("orders_history_page:")
    ):
        return await orders_callback(update, context)

    # Payment callbacks
    if data.startswith("pay_"):
        return await payments_callback(update, context)

    logger.info("Unhandled callback data: %s", data)


# ------------------------------
# TEXT ROUTER (USER MESSAGES)
# ------------------------------
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Delete user's text input globally (best-effort, private chat, <48h)
    await safe_delete_user_message(update)

    text = (update.message.text or "").strip()
    user_id = update.effective_user.id

    # ✅ Admin delivery reply handler
    if user_id in ADMIN_IDS and context.user_data.get("admin_deliver_waiting"):
        order_code = (context.user_data.get("admin_deliver_order_code") or "").strip()
        if not order_code:
            context.user_data.pop("admin_deliver_waiting", None)
            context.user_data.pop("admin_deliver_order_code", None)
            try:
                await update.message.reply_text(
                    "❌ Admin deliver state missing order code."
                )
            except Exception:
                pass
            return

        order = get_order_by_code(order_code)
        if not order:
            context.user_data.pop("admin_deliver_waiting", None)
            context.user_data.pop("admin_deliver_order_code", None)
            try:
                await update.message.reply_text("❌ Order not found.")
            except Exception:
                pass
            return

        pay_status = (order.get("pay_status") or "").lower().strip()
        if pay_status not in {"detected", "paid"}:
            context.user_data.pop("admin_deliver_waiting", None)
            context.user_data.pop("admin_deliver_order_code", None)
            try:
                await update.message.reply_text(
                    f"❌ Order {order_code} is not paid/detected yet."
                )
            except Exception:
                pass
            return

        delivery_text = text
        if not delivery_text:
            try:
                await update.message.reply_text(
                    "❌ Delivery text is empty. Send again."
                )
            except Exception:
                pass
            return

        customer_chat_id = order.get("user_id")
        if not customer_chat_id:
            context.user_data.pop("admin_deliver_waiting", None)
            context.user_data.pop("admin_deliver_order_code", None)
            try:
                await update.message.reply_text("❌ Order has no user_id.")
            except Exception:
                pass
            return

        # Build service.txt
        filename = "service.txt"
        content = (
            f"Order: {order_code}\n"
            f"Description: {order.get('description')}\n"
            f"Delivered at: {datetime.datetime.utcnow().isoformat()} UTC\n\n"
            f"{delivery_text}\n"
        )

        bio = io.BytesIO(content.encode("utf-8"))
        bio.name = filename

        try:
            # Send to user (persistent message)
            sent = await context.bot.send_document(
                chat_id=customer_chat_id,
                document=bio,
                caption=f"📦 Your order {order_code} has been delivered.",
            )

            # Save file_id for future re-send in history
            doc = getattr(sent, "document", None)
            file_id = getattr(doc, "file_id", None) if doc else None
            if file_id:
                save_delivery_file_by_code(
                    order_code, file_id=file_id, filename=filename
                )

            # Mark delivered
            mark_order_delivered(order_code)

            # Optional: auto-delete delivery message after 24 hours (if JobQueue exists)
            try:
                if tg_app.job_queue is not None:
                    tg_app.job_queue.run_once(
                        _delete_message_later,
                        when=24 * 3600,
                        data={
                            "chat_id": customer_chat_id,
                            "message_id": sent.message_id,
                        },
                        name=f"delmsg_{order_code}",
                    )
            except Exception:
                logger.exception("Failed to schedule delivery message delete (ignored)")

            try:
                await update.message.reply_text(
                    f"✅ Delivered {order_code} to user {customer_chat_id} as {filename}."
                )
            except Exception:
                pass

        except Exception:
            logger.exception("Admin delivery failed")
            try:
                await update.message.reply_text("❌ Failed to deliver. Try again.")
            except Exception:
                pass

        # Clear admin deliver state
        context.user_data.pop("admin_deliver_waiting", None)
        context.user_data.pop("admin_deliver_order_code", None)
        return

    # When user taps the persistent keyboard, clear flows and let main menu route
    if text in {"🧰 Tools", "🛒 Orders"}:
        # Clear all flow-related state (SSN + eSIM)
        for key in [
            "ssn_step",
            "first_name",
            "last_name",
            "type",
            "dob",
            "info",
            "from_ssn",
            "esim_step",
            "esim_email",
            "esim_duration",
            "esim_country",
            "custom_price_usd",
            "order_pending_description",
        ]:
            context.user_data.pop(key, None)

        return await handle_main_menu(update, context)

    # SSN text flow
    if context.user_data.get("ssn_step"):
        try:
            await handle_user_input(update, context)
        except Exception:
            logger.exception("SSN flow error")
            for key in [
                "ssn_step",
                "first_name",
                "last_name",
                "type",
                "dob",
                "info",
                "from_ssn",
            ]:
                context.user_data.pop(key, None)
            try:
                await update.message.reply_text(
                    "❌ Something went wrong. Please start again."
                )
            except Exception:
                pass
        return

    # eSIM email flow
    if context.user_data.get("esim_step") == "email":
        try:
            await handle_esim_email_input(update, context)
        except Exception:
            logger.exception("eSIM email flow error")
            for key in [
                "esim_step",
                "esim_email",
                "esim_duration",
                "esim_country",
                "custom_price_usd",
            ]:
                context.user_data.pop(key, None)
            try:
                await update.message.reply_text(
                    "❌ Something went wrong. Please start again."
                )
            except Exception:
                pass
        return

    # Default
    await handle_main_menu(update, context)


# ------------------------------
# HANDLERS REGISTRATION
# ------------------------------
tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("debug_last_order", debug_last_order))
tg_app.add_handler(CallbackQueryHandler(callback_router))
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
tg_app.add_handler(CommandHandler("admin", lambda u, c: admin_command(u, c, ADMIN_IDS)))


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
    ctype = (req.headers.get("content-type") or "").lower()

    # 1) Parse webhook body (form or json)
    try:
        if (
            "multipart/form-data" in ctype
            or "application/x-www-form-urlencoded" in ctype
        ):
            form = await req.form()
            payload = dict(form)
        else:
            payload = await req.json()
    except Exception:
        body = await req.body()
        logger.warning(
            "PLISIO WEBHOOK: parse failed content-type=%s body=%r", ctype, body[:500]
        )
        return {"ok": True}

    # 2) Unwrap {data:{...}} if present
    p = (
        payload.get("data")
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict)
        else payload
    )
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
    order_desc = (order.get("description") or "").strip().lower()

    paid_statuses = {"paid", "completed", "success", "confirmed", "finish", "finished"}
    expired_statuses = {"expired", "cancelled", "canceled", "failed", "error"}

    # -----------------------------
    # DETECTION LOGIC (NO SPAM)
    # -----------------------------
    detected_now = False

    received_amount = _to_float(p.get("received_amount"))
    if received_amount > 0:
        detected_now = True
    else:
        inv = None
        if isinstance(txn_id, str) and txn_id.strip():
            inv = await _fetch_plisio_invoice_details(txn_id.strip())

        if inv and isinstance(inv, dict):
            total = _to_float(
                inv.get("invoice_total_sum")
                or inv.get("amount")
                or inv.get("invoice_sum")
            )
            received = _to_float(inv.get("received_amount"))
            remaining = _to_float(inv.get("remaining_amount"))
            pending_amt = _to_float(inv.get("pending_amount"))

            if received > 0:
                detected_now = True
            elif total > 0 and remaining >= 0 and remaining < total:
                detected_now = True
            elif total > 0 and pending_amt >= 0 and pending_amt < total:
                detected_now = True

    # 1) If detected -> update DB + send ONCE
    if detected_now:
        if current_pay_status not in {"detected", "paid"}:
            update_payment_status_by_order_code(
                order_number, pay_status="detected", pay_txn_id=txn_id
            )
            try:
                update_order_status(order["id"], "processing")
            except Exception:
                logger.exception("update_order_status failed (ignored)")

            # ✅ notify admin ONCE when it first becomes detected
            try:
                if await ensure_telegram_ready():
                    asyncio.create_task(_notify_admin_new_paid_order(order))
            except Exception:
                logger.exception("Admin notify failed (ignored)")

            if chat_id and await ensure_telegram_ready():
                asyncio.create_task(
                    _safe_send_message(
                        chat_id,
                        f"✅ Payment detected for order {order_number}. Kindly wait while your order is being fulfilled.\n\nYou can return to Telegram now.",
                    )
                )

                # ✅ eSIM: schedule extra message 3 minutes after detected
                if order_desc.startswith("esim"):
                    try:
                        if tg_app.job_queue is None:
                            logger.warning(
                                "JobQueue not available; eSIM notice not scheduled."
                            )
                        else:
                            job_name = f"esim_notice_{order_number}"
                            existing = tg_app.job_queue.get_jobs_by_name(job_name)
                            if not existing:
                                tg_app.job_queue.run_once(
                                    send_esim_processing_notice,
                                    when=180,
                                    data={"chat_id": chat_id},
                                    name=job_name,
                                )
                    except Exception:
                        logger.exception("Failed to schedule eSIM notice (ignored)")
            else:
                logger.warning(
                    "Telegram not ready; detected message skipped for %s", order_number
                )

        return {"ok": True}

    # 2) Paid/confirmed -> update DB ONLY (NO user message)
    if status in paid_statuses:
        if current_pay_status != "paid":
            update_payment_status_by_order_code(
                order_number, pay_status="paid", pay_txn_id=txn_id
            )
        return {"ok": True}

    # 3) Expired/failed
    if status in expired_statuses:
        update_payment_status_by_order_code(
            order_number, pay_status="expired", pay_txn_id=txn_id
        )
        return {"ok": True}

    # Ignore noise if already detected/paid
    if current_pay_status in {"detected", "paid"}:
        return {"ok": True}

    # 4) Otherwise store status (optional)
    update_payment_status_by_order_code(
        order_number, pay_status=status or "pending", pay_txn_id=txn_id
    )
    return {"ok": True}


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/webhooks/plisio")
async def plisio_webhook_get():
    return {"ok": True}
