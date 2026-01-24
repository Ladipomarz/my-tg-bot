import os
import asyncio
import logging
import httpx
import datetime
import io
import re
import json

from fastapi import FastAPI, Request, Response
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
    Application,
    CallbackContext
)
from telegram.request import HTTPXRequest

from config import BOT_TOKEN
from utils.esim_pdf import build_esim_pdf_bytes
from utils.db import create_service_fetch_status_table
from handlers.otp_handler import handle_otp_text_input
from handlers.wallet import handle_wallet_text_input, wallet_callback

from utils.db import (
    create_tables,
    update_payment_status_by_order_code,
    get_order_by_code,
    expire_pending_order_if_needed,
    update_order_status,
    save_delivery_file_by_code,
    mark_order_delivered,
    save_delivery_meta_by_code,
    get_delivery_payload_by_code,
    add_user_balance_usd,
    get_user_balance_usd,
    mark_order_wallet_credited
)

from utils.auto_delete import safe_delete_user_message
from utils.auto_delete import delete_tracked_message


from menus.main_menu import get_main_menu
from menus.orders_menu import get_pending_order_menu

from handlers.servicelist import fetch_and_save_services
from handlers.start import start, handle_main_menu
from handlers.orders import orders_callback, debug_last_order
from handlers.payments import payments_callback
from handlers.tools import tools_callback, handle_user_input, handle_esim_email_input
from handlers.admin import admin_command, admin_callback

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()

PLISIO_API_KEY = os.getenv("PLISIO_API_KEY", "").strip()
PLISIO_BASE_URL = "https://api.plisio.net/api/v1"

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

tg_request = HTTPXRequest(
    connect_timeout=30.0,
    read_timeout=90.0,
    write_timeout=90.0,
    pool_timeout=90.0,
)

tg_app = ApplicationBuilder().token(BOT_TOKEN).request(tg_request).build()
TG_READY = False
TG_LOCK = asyncio.Lock()


# ------------------------------
# HELPERS
# ------------------------------
def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def extract_email_from_description(desc: str) -> str:
    """
    Your DB stores: "eSIM USA - 1 Month | Email: cc@vf.com"
    We auto-extract so admin doesn't type it.
    """
    if not desc:
        return ""
    m = re.search(r"email:\s*([^\s|]+)", desc, re.IGNORECASE)
    return m.group(1) if m else ""


def _parse_plan_days(desc: str) -> tuple[str, int]:
    """
    Your rule:
      1 month => +29 days
      3 months => +89 days
      1 year => +364 days
    """
    d = (desc or "").lower()
    if "3 month" in d or "3-month" in d or "3months" in d:
        return ("3 Month", 89)
    if "year" in d or "1 year" in d or "12 month" in d:
        return ("1 Year", 364)
    return ("1 Month", 29)


def _fmt_mmddyyyy(dt: datetime.datetime) -> str:
    return dt.strftime("%m/%d/%Y")


def _build_msn_txt(
    *,
    order_code: str,
    delivered_utc: datetime.datetime,
    full_name: str,
    dob: str,
    msn: str,
    address_history: str,
    warning: str | None,
) -> str:
    warning = (warning or "").strip()
    address_history = (address_history or "").strip()

    return (
        "☠️☠️☠️☠️☠️☠️☠️☠️☠️☠️\n"
        "        MSN DELIVERY\n"
        "☠️☠️☠️☠️☠️☠️☠️☠️☠️☠️\n\n"
        f"🔴 Order Code: {order_code}\n"
        "⚫ Country: USA\n"
        "🔴 Status: DELIVERED\n"
        f"🔴 Delivered (UTC): {_fmt_mmddyyyy(delivered_utc)}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💀 PERSONAL DETAILS\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚫ Full Name: {full_name}\n"
        f"⚫ DOB: {dob}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💀 MSN INFORMATION\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔴 MSN: {msn}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💀 ADDRESS HISTORY\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{address_history}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ WARNING\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔴 Do NOT share this file.\n"
        "🔴 Keep it private.\n"
        f"{('🔴 ' + warning) if warning else ''}\n"
    )


def _unpack_wizard_step(step):
    """
    Supports:
      (key, label) -> optional False
      (key, label, optional) -> optional bool
    """
    if isinstance(step, (list, tuple)):
        if len(step) == 3:
            return step[0], step[1], bool(step[2])
        if len(step) == 2:
            return step[0], step[1], False
    raise ValueError(f"Invalid wizard step format: {step!r}")


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
    for attempt in range(1, 4):
        try:
            await tg_app.bot.send_message(chat_id=chat_id, text=text)
            return
        except Exception as e:
            logger.exception("Telegram send_message failed attempt %s/3: %s", attempt, e)
            await asyncio.sleep(1.5 * attempt)


async def _notify_admin_new_paid_order(order: dict):
    """
    Admin gets notified ONCE when pay_status flips to detected.
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
        "Tap Deliver to start the wizard."
    )

    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Deliver", callback_data=f"admin_deliver:{order_code}")]]
    )

    for admin_id in ADMIN_IDS:
        try:
            await tg_app.bot.send_message(chat_id=admin_id, text=text, reply_markup=kb)
        except Exception:
            logger.exception("Failed to notify admin %s for order %s", admin_id, order_code)


async def _delete_message_later(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data.get("chat_id")
    message_id = job.data.get("message_id")
    if not chat_id or not message_id:
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


def _to_float(x) -> float:
    try:
        return float(str(x).strip())
    except Exception:
        return 0.0


async def _fetch_plisio_invoice_details(txn_id: str) -> dict | None:
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


async def send_esim_processing_notice(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data["chat_id"]
    msg = (
        "Usually Esims take 24 hours to be processed but we will make sure to make this faster "
        "do not reach out to support until 24 hours is elapsed and package not received"
    )
    await context.bot.send_message(chat_id=chat_id, text=msg)


# ------------------------------
# ADMIN REVIEW / EDIT HELPERS
# ------------------------------
def _wizard_build_summary(order_code: str, is_esim: bool, data: dict, qr_image_file_id: str | None) -> str:
    lines = [f"🧾 Review for {order_code}", ""]
    if is_esim:
        lines += [
            f"Email: {data.get('email','')}",
            f"Phone last4: {data.get('phone_last4','')}",
            f"Activation Code: {data.get('activation_code','')}",
            f"ICCID: {data.get('iccid','')}",
            f"QR Link: {data.get('qr_link','')}",
            f"QR Image: {'YES' if qr_image_file_id else 'NO'}",
        ]
    else:
        lines += [
            f"Full Name: {data.get('full_name','')}",
            f"DOB: {data.get('dob','')}",
            f"MSN: {data.get('msn','')}",
            "Address History:",
            (data.get("address_history") or "").strip() or "(empty)",
            f"Warning: {data.get('warning','')}",
        ]
    return "\n".join(lines)


def _admin_review_kb(order_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm & Deliver", callback_data=f"admin_confirm:{order_code}")],
        [InlineKeyboardButton("✏️ Edit one field", callback_data=f"admin_editpick:{order_code}")],
        [InlineKeyboardButton("✏️ Edit all & Resend", callback_data=f"admin_edit:{order_code}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"admin_cancelwiz:{order_code}")],
    ])


async def _admin_save_wiz_payload(context: ContextTypes.DEFAULT_TYPE):
    """
    Persist current wizard data to DB so delivered view shows latest values
    (needed for single-field edit flow).
    """
    wiz = context.user_data.get("admin_wizard") or {}
    order_code = (wiz.get("order_code") or "").strip()
    if not order_code:
        return
    try:
        payload = dict(wiz.get("data") or {})
        payload["qr_image_file_id"] = wiz.get("qr_image_file_id") or ""
        save_delivery_meta_by_code(order_code, payload=payload)
    except Exception:
        logger.exception("Failed to save wizard payload (ignored)")


async def _admin_show_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wiz = context.user_data.get("admin_wizard") or {}
    order_code = (wiz.get("order_code") or "").strip()
    if not order_code:
        context.user_data.pop("admin_wizard", None)
        await update.message.reply_text("❌ Wizard missing order code.")
        return

    order = get_order_by_code(order_code) or {}
    desc = (order.get("description") or "").strip()
    is_esim = desc.lower().startswith("esim")

    data = wiz.get("data") or {}
    qr_img = wiz.get("qr_image_file_id") or ""

    wiz["stage"] = "review"
    context.user_data["admin_wizard"] = wiz

    summary = _wizard_build_summary(order_code, is_esim, data, qr_img)
    await update.message.reply_text(summary, reply_markup=_admin_review_kb(order_code))
    
    if is_esim:
       email_auto = extract_email_from_description(desc).strip()
    if email_auto and not (data.get("email") or "").strip():
        data["email"] = email_auto
        wiz["data"] = data
        context.user_data["admin_wizard"] = wiz



def _admin_edit_picker_kb(order_code: str, steps: list) -> InlineKeyboardMarkup:
    rows = []
    for i, step in enumerate(steps):
        if isinstance(step, (tuple, list)) and len(step) >= 2:
            key = step[0]
            rows.append([InlineKeyboardButton(f"✏️ Edit {key}", callback_data=f"admin_editset:{order_code}:{i}")])
    rows.append([InlineKeyboardButton("⬅ Back", callback_data=f"admin_view:{order_code}")])
    return InlineKeyboardMarkup(rows)


# ------------------------------
# ADMIN WIZARD HELPERS
# ------------------------------
async def _admin_send_next_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wiz = context.user_data.get("admin_wizard") or {}
    steps = wiz.get("steps") or []
    idx = int(wiz.get("idx") or 0)

    # After last step -> REVIEW (NOT deliver immediately)
    if idx >= len(steps):
        await _admin_show_review(update, context)
        return

    key, label, optional = _unpack_wizard_step(steps[idx])
    _ = key

    prompt = await update.message.reply_text(
        f"✅ Deliver wizard for {wiz.get('order_code')}\n\n"
        f"Send:\n{label}\n\n"
        + ("Type: skip (optional)" if optional else "Type the value")
        + "\nType: cancel (stop wizard)"
        + "\nType: back (previous field)"
    )
    wiz["prompt_msg_id"] = prompt.message_id
    wiz["stage"] = "input"
    context.user_data["admin_wizard"] = wiz


async def _admin_finish_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wiz = context.user_data.get("admin_wizard") or {}
    order_code = wiz.get("order_code")
    if not order_code:
        context.user_data.pop("admin_wizard", None)
        await update.message.reply_text("❌ Wizard missing order code.")
        return

    order = get_order_by_code(order_code)
    if not order:
        context.user_data.pop("admin_wizard", None)
        await update.message.reply_text("❌ Order not found.")
        return

    customer_chat_id = order.get("user_id")
    if not customer_chat_id:
        context.user_data.pop("admin_wizard", None)
        await update.message.reply_text("❌ Order has no user_id.")
        return

    desc = (order.get("description") or "").strip()
    is_esim = desc.lower().startswith("esim")

    data = wiz.get("data") or {}
    delivered_utc = datetime.datetime.utcnow()

    try:
        if is_esim:
            plan_name, plan_days = _parse_plan_days(desc)
            expires = delivered_utc + datetime.timedelta(days=plan_days)

            email = extract_email_from_description(desc).strip() or (data.get("email") or "").strip()
            if not email:
                raise ValueError("Missing required email for eSIM delivery")

            phone_last4 = (data.get("phone_last4") or "").strip()
            phone_mask = f"XXX-XXX-{phone_last4}" if phone_last4 else "XXX-XXX-____"

            pdf_buf = build_esim_pdf_bytes(
                order_code=order_code,
                phone_number_masked=phone_mask,
                plan_name=plan_name,
                plan_expires_str=_fmt_mmddyyyy(expires),
                email=email,
                activation_code=(data.get("activation_code") or "").strip(),
                iccid=(data.get("iccid") or "").strip(),
                qr_link=(data.get("qr_link") or "").strip(),
            )
            pdf_buf.name = "service.pdf"

            sent = await context.bot.send_document(
                chat_id=customer_chat_id,
                document=pdf_buf,
                caption=f"📦 Your order {order_code} is delivered",
            )

            doc = getattr(sent, "document", None)
            file_id = getattr(doc, "file_id", None) if doc else None
            if file_id:
                save_delivery_file_by_code(order_code, file_id=file_id, filename="service.pdf")

            qr_img_id = wiz.get("qr_image_file_id")
            if qr_img_id:
                try:
                    await context.bot.send_photo(
                        chat_id=customer_chat_id,
                        photo=qr_img_id,
                        caption=f"📷 QR Code for {order_code}",
                    )
                except Exception:
                    logger.exception("Failed to send QR image (ignored)")

        else:
            txt = _build_msn_txt(
                order_code=order_code,
                delivered_utc=delivered_utc,
                full_name=(data.get("full_name") or "").strip(),
                dob=(data.get("dob") or "").strip(),
                msn=(data.get("msn") or "").strip(),
                address_history=(data.get("address_history") or "").strip(),
                warning=(data.get("warning") or "").strip(),
            )

            bio = io.BytesIO(txt.encode("utf-8"))
            bio.name = "service.txt"

            old_msg_id = order.get("delivered_message_id")
            if old_msg_id:
                try:
                    await context.bot.delete_message(chat_id=customer_chat_id, message_id=int(old_msg_id))
                except Exception:
                    pass

            sent = await context.bot.send_document(
                chat_id=customer_chat_id,
                document=bio,
                caption=f"📦 Your order {order_code} is delivered",
            )

            doc = getattr(sent, "document", None)
            file_id = getattr(doc, "file_id", None) if doc else None
            if file_id:
                save_delivery_file_by_code(order_code, file_id=file_id, filename="service.txt")

        mark_order_delivered(order_code)

        # Save payload for later viewing/editing
        try:
            payload = dict(wiz.get("data") or {})
            payload["qr_image_file_id"] = wiz.get("qr_image_file_id") or ""
            save_delivery_meta_by_code(
                order_code,
                payload=payload,
                delivered_message_id=sent.message_id,
            )
        except Exception:
            logger.exception("Failed to save delivery payload (ignored)")

        # auto-delete delivery msg after 24h (optional)
        try:
            if tg_app.job_queue is not None:
                tg_app.job_queue.run_once(
                    _delete_message_later,
                    when=24 * 3600,
                    data={"chat_id": customer_chat_id, "message_id": sent.message_id},
                    name=f"delmsg_{order_code}",
                )
        except Exception:
            logger.exception("Failed to schedule delivery delete (ignored)")

        context.user_data.pop("admin_wizard", None)
        await update.message.reply_text(f"✅ Delivered {order_code}.")

    except Exception:
        logger.exception("Admin delivery failed")
        context.user_data.pop("admin_wizard", None)
        await update.message.reply_text("❌ Failed to deliver. Wizard cancelled.")


async def _admin_capture_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    In wizard mode, accept the next admin message as the next field.
    """
    user_id = update.effective_user.id
    if not _is_admin(user_id):
        return False

    wiz = context.user_data.get("admin_wizard")
    if not wiz:
        return False

    steps = wiz.get("steps") or []
    idx = int(wiz.get("idx") or 0)
    if idx >= len(steps):
        return False

    key, _label, optional = _unpack_wizard_step(steps[idx])
    val = (update.message.text or "").strip()
    low = val.lower().strip()

    if low == "cancel":
        context.user_data.pop("admin_wizard", None)
        await update.message.reply_text("✅ Wizard cancelled.")
        return True

    if low == "back":
        wiz["idx"] = max(0, idx - 1)
        context.user_data["admin_wizard"] = wiz
        await _admin_send_next_prompt(update, context)
        return True

    # Skip handling
    if low == "skip":
        if optional:
            if key == "qr_image":
                wiz["idx"] = idx + 1
                context.user_data["admin_wizard"] = wiz

                if (wiz.get("edit_mode") or "").lower() == "single":
                    await _admin_save_wiz_payload(context)
                    await _admin_show_review(update, context)
                    return True

                await _admin_send_next_prompt(update, context)
                return True

            wiz.setdefault("data", {})[key] = ""
            wiz["idx"] = idx + 1
            context.user_data["admin_wizard"] = wiz

            if (wiz.get("edit_mode") or "").lower() == "single":
                await _admin_save_wiz_payload(context)
                await _admin_show_review(update, context)
                return True

            await _admin_send_next_prompt(update, context)
            return True

        await update.message.reply_text("❌ This field cannot be skipped.")
        return True

    # Empty protection
    if not val:
        await update.message.reply_text("❌ Empty value. Send again.")
        return True

    # If admin mistakenly sends text during qr_image step, guide them
    if key == "qr_image":
        await update.message.reply_text("❌ Please send a photo/document for QR image, or type 'skip'.")
        return True

    wiz.setdefault("data", {})[key] = val
    wiz["idx"] = idx + 1
    context.user_data["admin_wizard"] = wiz

    # If editing single field, save -> review
    if (wiz.get("edit_mode") or "").lower() == "single":
        await _admin_save_wiz_payload(context)
        await _admin_show_review(update, context)
        return True

    await _admin_send_next_prompt(update, context)
    return True


async def media_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles QR image upload step (photo or document) during admin wizard.
    """
    user_id = update.effective_user.id
    if not _is_admin(user_id):
        return

    wiz = context.user_data.get("admin_wizard")
    if not wiz:
        return

    steps = wiz.get("steps") or []
    idx = int(wiz.get("idx") or 0)
    if idx >= len(steps):
        return

    key, _label, _optional = _unpack_wizard_step(steps[idx])
    if key != "qr_image":
        return

    file_id = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.document:
        file_id = update.message.document.file_id

    if not file_id:
        await update.message.reply_text("❌ Send a photo/document, or type 'skip'.")
        return

    wiz["qr_image_file_id"] = file_id
    wiz["idx"] = idx + 1
    context.user_data["admin_wizard"] = wiz

    # If single edit, save -> review
    if (wiz.get("edit_mode") or "").lower() == "single":
        await _admin_save_wiz_payload(context)
        await _admin_show_review(update, context)
        return

    await _admin_send_next_prompt(update, context)


def _build_esim_steps(desc: str, saved: dict | None = None):
    saved = saved or {}
    email_auto = extract_email_from_description(desc).strip()

    steps = []
    if not email_auto:
        steps.append(("email", "🟡 Customer Email (required)", False))

    steps += [
        ("phone_last4", "🟡 Phone last 4 digits (example: 0451)", False),
        ("activation_code", "🟡 Activation Code", False),
        ("iccid", "🟡 ICCID", False),
        ("qr_link", "🟡 QR Code Link (optional) — type 'skip'", True),
        ("qr_image", "🟡 Upload QR Image (optional) — send photo OR type 'skip'", True),
    ]

    data0 = {
        "email": email_auto or (saved.get("email") or ""),
        "phone_last4": saved.get("phone_last4") or "",
        "activation_code": saved.get("activation_code") or "",
        "iccid": saved.get("iccid") or "",
        "qr_link": saved.get("qr_link") or "",
    }
    qr_img = saved.get("qr_image_file_id") or ""
    return steps, data0, qr_img


def _build_msn_steps(saved: dict | None = None):
    saved = saved or {}
    steps = [
        ("full_name", "🔴 Full Name", False),
        ("dob", "🔴 DOB (example: 01/31/1998)", False),
        ("msn", "🔴 MSN", False),
        ("address_history", "⚫ Address History (paste multi-line if needed)", False),
        ("warning", "⚠️ Extra Warning/Note (optional) — type 'skip'", True),
    ]
    data0 = {
        "full_name": saved.get("full_name") or "",
        "dob": saved.get("dob") or "",
        "msn": saved.get("msn") or "",
        "address_history": saved.get("address_history") or "",
        "warning": saved.get("warning") or "",
    }
    return steps, data0


# ------------------------------
# CALLBACK ROUTER
# ------------------------------
async def debug_payload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /debug_payload ORD-XXXXX")
        return

    code = context.args[0].strip()
    payload = get_delivery_payload_by_code(code)

    if not payload:
        await update.message.reply_text(f"❌ No payload stored for {code}")
        return

    await update.message.reply_text(
        f"✅ Payload stored for {code}\nKeys: {list(payload.keys())}\n\n{payload}"
    )


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data:
        return
    
    data = q.data.strip()  # Clean up the data
    print("callback_router hit:", data)

    
    
    # Route OTP/tools/service callbacks into tools_callback
    if data.startswith(("tool_", "otp_", "service_", "esim_")):
        await tools_callback(update, context)
        return

    
    await delete_tracked_message(context, q.message.chat_id, "pending_prompt_msg_id")

    data = (q.data or "").strip()
    user_id = q.from_user.id

    try:
        await q.answer(cache_time=2)
    except Exception as e:
        logger.warning("q.answer() failed (ignored): %s", e)

    logger.info("callback_router got data=%r", data)

    # Back to main (everyone)
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
    
    if data.startswith("wallet_") or data == "back_main":
        return await wallet_callback(update, context)


    # ADMIN list menu + paging (admin.py)
    if data == "admin_menu" or data.startswith("admin_paid:") or data.startswith("admin_delivered:"):
        return await admin_callback(update, context, ADMIN_IDS)

    # ✅ Admin view delivered payload (PREVIEW)
    if data.startswith("admin_view:"):
        if not _is_admin(user_id):
            return

        order_code = data.split(":", 1)[1].strip()
        order = get_order_by_code(order_code) or {}
        desc = (order.get("description") or "").strip()
        is_esim = desc.lower().startswith("esim")

        saved = get_delivery_payload_by_code(order_code) or {}

        summary = _wizard_build_summary(
            order_code=order_code,
            is_esim=is_esim,
            data=saved,
            qr_image_file_id=(saved.get("qr_image_file_id") or ""),
        )

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Edit one field", callback_data=f"admin_editpick:{order_code}")],
            [InlineKeyboardButton("✏️ Edit all & Resend", callback_data=f"admin_edit:{order_code}")],
            [InlineKeyboardButton("⬅ Back", callback_data="admin_menu")],
        ])

        try:
            await q.edit_message_text(summary, reply_markup=kb)
        except Exception:
            await q.message.reply_text(summary, reply_markup=kb)
        return

    # ✅ ADMIN confirm & deliver
    if data.startswith("admin_confirm:"):
        if not _is_admin(user_id):
            return
        order_code = data.split(":", 1)[1].strip()
        wiz = context.user_data.get("admin_wizard") or {}
        if (wiz.get("order_code") or "").strip() != order_code:
            await q.message.reply_text("❌ No active wizard for this order.")
            return

        try:
            await q.edit_message_text(f"✅ Delivering {order_code}…")
        except Exception:
            pass

        await _admin_finish_delivery(Update(update.update_id, message=q.message), context)
        return

    # ✅ Admin: pick a field to edit (single-field edit)
    if data.startswith("admin_editpick:"):
        if not _is_admin(user_id):
            return
        order_code = data.split(":", 1)[1].strip()

        order = get_order_by_code(order_code) or {}
        desc = (order.get("description") or "").strip()
        is_esim = desc.lower().startswith("esim")

        saved = get_delivery_payload_by_code(order_code) or {}

        if is_esim:
            steps, data0, qr_img = _build_esim_steps(desc, saved)
        else:
            steps, data0 = _build_msn_steps(saved)
            qr_img = ""

        context.user_data["admin_wizard"] = {
            "order_code": order_code,
            "steps": steps,
            "idx": 0,
            "data": data0,
            "prompt_msg_id": None,
            "qr_image_file_id": qr_img,
            "edit_mode": "single",
        }

        try:
            await q.edit_message_text(
                f"Select a field to edit for {order_code}:",
                reply_markup=_admin_edit_picker_kb(order_code, steps),
            )
        except Exception:
            await q.message.reply_text(
                f"Select a field to edit for {order_code}:",
                reply_markup=_admin_edit_picker_kb(order_code, steps),
            )
        return

    # ✅ Admin: jump to that field index and prompt for new value
    if data.startswith("admin_editset:"):
        if not _is_admin(user_id):
            return
        try:
            _pfx, order_code, idx_s = data.split(":", 2)
            new_idx = int(idx_s)
        except Exception:
            await q.message.reply_text("❌ Invalid field selection.")
            return

        wiz = context.user_data.get("admin_wizard") or {}
        if (wiz.get("order_code") or "").strip() != order_code:
            await q.message.reply_text("❌ No active wizard for this order. Tap Edit again.")
            return

        wiz["idx"] = max(0, new_idx)
        context.user_data["admin_wizard"] = wiz

        # IMPORTANT: only prompt once (no extra "send value" message)
        await _admin_send_next_prompt(Update(update.update_id, message=q.message), context)
        return

    # ✅ ADMIN cancel wizard
    if data.startswith("admin_cancelwiz:"):
        if not _is_admin(user_id):
            return
        context.user_data.pop("admin_wizard", None)
        try:
            await q.edit_message_text("✅ Wizard cancelled.")
        except Exception:
            pass
        return

    # ✅ ADMIN edit/resend delivered (edit ALL fields)
    if data.startswith("admin_edit:"):
        if not _is_admin(user_id):
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

        saved = get_delivery_payload_by_code(order_code) or {}

        desc = (order.get("description") or "").strip()
        is_esim = desc.lower().startswith("esim")

        if is_esim:
            email_auto = extract_email_from_description(desc).strip()
            steps = []
            if not email_auto:
                steps.append(("email", "🟡 Customer Email (required)", False))
            steps += [
                ("phone_last4", "🟡 Phone last 4 digits (example: 0451)", False),
                ("activation_code", "🟡 Activation Code", False),
                ("iccid", "🟡 ICCID", False),
                ("qr_link", "🟡 QR Code Link (optional) — type 'skip'", True),
                ("qr_image", "🟡 Upload QR Image (optional) — send photo OR type 'skip'", True),
            ]
            data0 = {
                "email": email_auto or (saved.get("email") or ""),
                "phone_last4": saved.get("phone_last4") or "",
                "activation_code": saved.get("activation_code") or "",
                "iccid": saved.get("iccid") or "",
                "qr_link": saved.get("qr_link") or "",
            }
            qr_img = saved.get("qr_image_file_id") or ""
        else:
            steps = [
                ("full_name", "🔴 Full Name", False),
                ("dob", "🔴 DOB (example: 01/31/1998)", False),
                ("msn", "🔴 MSN", False),
                ("address_history", "⚫ Address History (paste multi-line if needed)", False),
                ("warning", "⚠️ Extra Warning/Note (optional) — type 'skip'", True),
            ]
            data0 = {
                "full_name": saved.get("full_name") or "",
                "dob": saved.get("dob") or "",
                "msn": saved.get("msn") or "",
                "address_history": saved.get("address_history") or "",
                "warning": saved.get("warning") or "",
            }
            qr_img = ""

        context.user_data["admin_wizard"] = {
            "order_code": order_code,
            "steps": steps,
            "idx": 0,
            "data": data0,
            "prompt_msg_id": None,
            "qr_image_file_id": qr_img,
            "edit_mode": "all",
        }

        try:
            await q.edit_message_text(
                f"✏️ Edit & Resend started for {order_code}\n\n"
                "Send the new values one-by-one.\n"
                "Type the new value, or type 'skip' for optional fields.\n"
                "Type 'back' to go previous field, 'cancel' to stop."
            )
        except Exception:
            pass

        try:
            await _admin_send_next_prompt(Update(update.update_id, message=q.message), context)
        except Exception:
            try:
                await q.message.reply_text("❌ Failed to start edit wizard.")
            except Exception:
                pass
        return

    # ✅ ADMIN deliver wizard start
    if data.startswith("admin_deliver:"):
        if not _is_admin(user_id):
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

        if pay_status not in {"detected", "paid"}:
            try:
                await q.edit_message_text(f"❌ Order {order_code} is not paid/detected yet.")
            except Exception:
                pass
            return

        if delivery_status == "delivered":
            try:
                await q.edit_message_text(f"✅ Order {order_code} already delivered.")
            except Exception:
                pass
            return

        desc = (order.get("description") or "").strip()
        is_esim = desc.lower().startswith("esim")

        if is_esim:
            email_auto = extract_email_from_description(desc).strip()
            steps = []
            if not email_auto:
                steps.append(("email", "🟡 Customer Email (required)", False))
            steps += [
                ("phone_last4", "🟡 Phone last 4 digits (example: 0451)", False),
                ("activation_code", "🟡 Activation Code", False),
                ("iccid", "🟡 ICCID", False),
                ("qr_link", "🟡 QR Code Link (optional) — type 'skip'", True),
                ("qr_image", "🟡 Upload QR Image (optional) — send photo OR type 'skip'", True),
            ]
        else:
            steps = [
                ("full_name", "🔴 Full Name", False),
                ("dob", "🔴 DOB (example: 01/31/1998)", False),
                ("msn", "🔴 MSN", False),
                ("address_history", "⚫ Address History (paste multi-line if needed)", False),
                ("warning", "⚠️ Extra Warning/Note (optional) — type 'skip'", True),
            ]
            
        email_auto = extract_email_from_description(desc).strip()
        context.user_data["admin_wizard"] = {
            "order_code": order_code,
            "steps": steps,
            "idx": 0,
            "data": {"email": email_auto} if (is_esim and email_auto) else {},
            "prompt_msg_id": None,
            "qr_image_file_id": None,
            "edit_mode": "all",
        }

        try:
            await q.edit_message_text(
                f"✅ Deliver wizard started for {order_code}\n\n"
                "I will ask you for fields one-by-one."
            )
        except Exception:
            pass

        try:
            await _admin_send_next_prompt(Update(update.update_id, message=q.message), context)
        except Exception:
            logger.exception("Failed to send first admin wizard prompt")
            try:
                await q.message.reply_text("❌ Failed to start wizard. Try again.")
            except Exception:
                pass
        return

    # ✅ BLOCK admin from user UI callbacks
    if _is_admin(user_id):
        if (
            data.startswith("tool_")
            or data.startswith("orders_")
            or data.startswith("pay_")
            or data in {"esim_services"}
            or data.startswith("esim_duration:")
        ):
            try:
                await q.edit_message_text(
                    "Admin menu:",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("Open Admin Menu", callback_data="admin_menu")]]
                    ),
                )
            except Exception:
                pass
            return

    # ------------------------------
    # USER ROUTES
    # ------------------------------
    is_tools_related = (
        data.startswith("tool_")
        or data == "esim_services"
        or data.startswith("esim_duration:")
        or data in {"msn_back", "cancel_msn"}
    )
    if is_tools_related:
        pending = expire_pending_order_if_needed(user_id)
        if pending and pending.get("status") == "pending":
            pay_status = (pending.get("pay_status") or "").lower().strip()
            if pay_status in {"pending", "", "new"}:
                try:
                    await delete_tracked_message(context, q.message.chat_id, "pending_prompt_msg_id")

                    await q.edit_message_text(
                        f"🕒 You have a pending order {pending['order_code']}.\nWhat do you want to do?",
                        reply_markup=get_pending_order_menu(),
                    )

                    context.user_data["pending_prompt_msg_id"] = q.message.message_id

                except Exception:
                    logger.exception("edit_message_text failed (ignored)")
                return
        return await tools_callback(update, context)

    if (
        data.startswith("orders_")
        or data.startswith("order_file:")
        or data.startswith("orders_history_page:")
    ):
        return await orders_callback(update, context)

    if data.startswith("pay_"):
        return await payments_callback(update, context)

    logger.info("Unhandled callback data: %s", data)


# ------------------------------
# TEXT ROUTER
# ------------------------------
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # inside text_router, very early:
    if await handle_otp_text_input(update, context):
        return

    # Admin wizard capture FIRST
    if await _admin_capture_text(update, context):
        return
    
    if await handle_otp_text_input(update, context):
        return

    if await handle_wallet_text_input(update, context):
        return


    # best-effort delete user message
    await safe_delete_user_message(update)

    user_id = update.effective_user.id
    text = (update.message.text or "").strip()

    # delete pending warning on ANY new text / keypad press
    await delete_tracked_message(
        context,
        update.effective_chat.id,
        "pending_prompt_msg_id",
    )

    # Admin-only: no user menus
    if _is_admin(user_id) and text in {"🧰 Tools", "🛒 Orders"}:
        context.user_data.pop("admin_wizard", None)
        await update.message.reply_text("Admin menu: use /admin")
        return

    # User main keyboard
    if text in {"🧰 Tools", "🛒 Orders", "💰 Wallet"}:
        pending = None  # prevent UnboundLocalError no matter what

        # if Tools clicked and there is a pending order, redirect to pending page
        if text == "🧰 Tools":
            pending = expire_pending_order_if_needed(user_id)

        if pending and pending.get("status") == "pending":
            pay_status = (pending.get("pay_status") or "").lower().strip()
            if pay_status in {"pending", "", "new"}:
                await delete_tracked_message(
                    context,
                    update.effective_chat.id,
                    "pending_prompt_msg_id",
                )

                msg = await update.message.reply_text(
                    f"🕒 You have a pending order {pending['order_code']}.\nWhat do you want to do?",
                    reply_markup=get_pending_order_menu(),
                )

                if msg:
                    context.user_data["pending_prompt_msg_id"] = msg.message_id
                return

        for key in [
            "msn_step",
            "first_name",
            "last_name",
            "type",
            "dob",
            "info",
            "from_msn",
            "esim_step",
            "esim_email",
            "esim_duration",
            "esim_country",
            "custom_price_usd",
            "order_pending_description",
        ]:
            context.user_data.pop(key, None)

        return await handle_main_menu(update, context)

    # MSN flow
    if context.user_data.get("msn_step"):
        try:
            await handle_user_input(update, context)
        except Exception:
            logger.exception("MSN flow error")
            for key in ["msn_step", "first_name", "last_name", "type", "dob", "info", "from_msn"]:
                context.user_data.pop(key, None)
            try:
                await update.message.reply_text("❌ Something went wrong. Please start again.")
            except Exception:
                pass
        return

    # eSIM email flow (user flow)
    if context.user_data.get("esim_step") == "email":
        try:
            await handle_esim_email_input(update, context)
        except Exception:
            logger.exception("eSIM email flow error")
            for key in ["esim_step", "esim_email", "esim_duration", "esim_country", "custom_price_usd"]:
                context.user_data.pop(key, None)
            try:
                await update.message.reply_text("❌ Something went wrong. Please start again.")
            except Exception:
                pass
        return

    await handle_main_menu(update, context)


# ------------------------------
# /admin wrapper
# ------------------------------
async def admin_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await admin_command(update, context, ADMIN_IDS)


# ------------------------------
# REGISTER HANDLERS
# ------------------------------
tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("admin", admin_entry))
tg_app.add_handler(CommandHandler("debug_last_order", debug_last_order))
tg_app.add_handler(CommandHandler("debug_payload", debug_payload))
tg_app.add_handler(CallbackQueryHandler(callback_router))


# IMPORTANT: media before text (QR upload wizard)
# First: OTP text handler
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router), group=0)
# Lastly: Your media router
tg_app.add_handler(MessageHandler((filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND, media_router))


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


# ------------------------------
# PLISIO WEBHOOK
# ------------------------------
@app.post("/webhooks/plisio")
async def plisio_webhook(req: Request):
    ctype = (req.headers.get("content-type") or "").lower()

    try:
        if "multipart/form-data" in ctype or "application/x-www-form-urlencoded" in ctype:
            form = await req.form()
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
    chat_id = order.get("user_id")
    current_pay_status = (order.get("pay_status") or "").lower().strip()
    order_desc = (order.get("description") or "").strip().lower()

    paid_statuses = {"paid", "completed", "success", "confirmed", "finish", "finished"}
    expired_statuses = {"expired", "cancelled", "canceled", "failed", "error"}

    detected_now = False

    received_amount = _to_float(p.get("received_amount"))
    if received_amount > 0:
        detected_now = True
    else:
        inv = None
        if isinstance(txn_id, str) and txn_id.strip():
            inv = await _fetch_plisio_invoice_details(txn_id.strip())

        if inv and isinstance(inv, dict):
            total = _to_float(inv.get("invoice_total_sum") or inv.get("amount") or inv.get("invoice_sum"))
            received = _to_float(inv.get("received_amount"))
            remaining = _to_float(inv.get("remaining_amount"))
            pending_amt = _to_float(inv.get("pending_amount"))

            if received > 0:
                detected_now = True
            elif total > 0 and remaining >= 0 and remaining < total:
                detected_now = True
            elif total > 0 and pending_amt >= 0 and pending_amt < total:
                detected_now = True

    if detected_now:
        if current_pay_status not in {"detected", "paid"}:
            update_payment_status_by_order_code(order_number, pay_status="detected", pay_txn_id=txn_id)
            try:
                update_order_status(order["id"], "processing")
            except Exception:
                logger.exception("update_order_status failed (ignored)")

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

                if order_desc.startswith("esim"):
                    try:
                        if tg_app.job_queue is not None:
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

        return {"ok": True}

    if status in paid_statuses:
        if current_pay_status != "paid":
            update_payment_status_by_order_code(order_number, pay_status="paid", pay_txn_id=txn_id)
        return {"ok": True}
    
    if order and (order.get("order_type") == "wallet_topup" or (order.get("description") or "").startswith("WALLET_TOPUP:")):
        if not order.get("wallet_credited"):
            amt = order.get("amount_usd") or 0
            if amt:
                add_user_balance_usd(order["user_id"], float(amt))
                mark_order_wallet_credited(order_number)

                new_bal = get_user_balance_usd(order["user_id"])
                await app.bot.send_message(
                    chat_id=order["user_id"],
                    text=f"✅ Wallet topped up: ${float(amt):.2f}\nNew balance: ${new_bal:.2f}",
                )


    if status in expired_statuses:
        update_payment_status_by_order_code(order_number, pay_status="expired", pay_txn_id=txn_id)
        return {"ok": True}

    if current_pay_status in {"detected", "paid"}:
        return {"ok": True}

    update_payment_status_by_order_code(order_number, pay_status=status or "pending", pay_txn_id=txn_id)
    return {"ok": True}


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/webhooks/plisio")
async def plisio_webhook_get():
    return {"ok": True}


from utils.db import reset_services_fetch_state




@app.on_event("startup")
async def on_startup():
    print("Fast API up")

    create_tables()
    create_service_fetch_status_table()

    # one-time force refresh by env var
    if os.getenv("FORCE_SERVICES_REFETCH") == "1":
        reset_services_fetch_state(clear_services=False)  # keep existing, just allow missing inserts

    # Run the blocking fetch in a background thread (SAFE)
    #task = asyncio.create_task(asyncio.to_thread(fetch_and_save_services))

    def _log_task_result(t: asyncio.Task):
        exc = t.exception()
        if exc:
            import logging
            logging.getLogger("servicelist").exception(
                "Background service task crashed",
                exc_info=exc
            )

    #task.add_done_callback(_log_task_result)

    # Start telegram bootstrap too
    asyncio.create_task(_background_telegram_bootstrap())
