import os
import asyncio
import logging
import httpx
import datetime
import io
import re
import json
import traceback
import html
from config import SUPPORT_HANDLE
from supportbot import run_support_bot
from telegram.helpers import escape
import html

from fastapi import FastAPI, Request, Response
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton,BotCommand
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
from utils.auto_delete import safe_send
from handlers.admin import fix_db_sequence,rescue_my_number,admin_get_stats
from utils.helper import notify_admin
from handlers.menu_commands import help_cmd
from handlers.global_flow import handle_global_type, handle_global_duration, handle_global_country_selection
from config import BOT_TOKEN
from utils.esim_pdf import build_esim_pdf_bytes
from utils.db import create_service_fetch_status_table
from handlers.otp_handler import handle_otp_text_input
from handlers.wallet import handle_wallet_text_input, wallet_callback
from handlers.menu_commands import register_side_menu, setup_bot_profile

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
    mark_order_wallet_credited,
    create_wallet_transactions_table,
    get_all_active_rentals,
    auto_expire_rentals,
    update_order_actual_amount,
    get_all_user_ids
)

from utils.auto_delete import safe_delete_user_message
from utils.auto_delete import delete_tracked_message


from menus.main_menu import get_main_menu
from menus.orders_menu import get_pending_order_menu

from handlers.servicelist import fetch_and_save_services
from handlers.service_list_flow import resend_otp_menu
from handlers.global_flow import process_global_country_input

from handlers.start import start, handle_main_menu
from handlers.orders import orders_callback, debug_last_order
from handlers.payments import payments_callback
from handlers.tools import tools_callback, handle_user_input, handle_esim_email_input
from handlers.admin import admin_command, admin_callback,admin_check_balance
from handlers.wallet_continue import open_wallet_menu
from handlers.rental import (
handle_rental_product_id,
handle_state_or_random
,handle_rental_state,
confirm_rental,
my_rentals_menu,
manage_rental_menu,
my_rentals_menu,
check_sms_action,
handle_rental_universal,
trigger_extension_menu,
handle_extension_text,
scheduled_expire_rental,
resend_rental_menu,
scheduled_expire_rental, 
scheduled_6h_reminder,
force_test_auto_extend,
scheduled_auto_extend_plus_daily_check,
test_6h_warning,
test_expire_alarm

)

# In bot.py
from handlers.global_flow import (
    handle_global_start, 
    handle_global_type, 
    handle_global_duration, 
    handle_global_country_selection,
    handle_other_countries_click,
    process_global_country_input
)


# 1. SET THE GLOBAL RULE (Change this from DEBUG to INFO)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger("server")
logger.setLevel(logging.DEBUG)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.INFO)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

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


# ------------------------------
# HELPERS
# ------------------------------

# 🚨 THE GLOBAL SAFETY NET 🚨
async def global_error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Catches ALL unhandled crashes, hides the error from the user, 
    and sends the raw traceback to the Admins.
    """
    logger.error("Exception while handling an update:", exc_info=context.error)
    if context.user_data:
        context.user_data.clear()

    # 1. Send the white-labeled error to the user WITH the support link
    if update and update.effective_chat:
        safe_message = (
            "❌ <b>System Error</b>\n"
            "An unexpected error occurred. Please try again.\n\n"
            f"🛠 <b>Need help? Contact {SUPPORT_HANDLE}</b>"
        )
        
        try:
            await safe_send(
                update,
                context,
                chat_id=update.effective_chat.id,
                text=safe_message,
                parse_mode="HTML"
                
            )
        except Exception:
            pass

    # 2. THE ADMIN ALERT
    if ADMIN_IDS:
        user_id = update.effective_user.id if update and update.effective_user else "Unknown"
        
        # Create a short, single-line summary
        error_text = html.escape(str(context.error))
        admin_msg = f"🚨 <b>CRASH</b> | User: <code>{user_id}</code> | Error: {error_text}"
        
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=admin_msg, parse_mode="HTML")
            except Exception:
                pass
            
            
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
            #await setup_bot_profile(tg_app)
             
            # ---------------------------------------------------------
            # 🚀 THE ENTERPRISE HYBRID STARTUP (DUAL-ALARM UPGRADE)
            
            # 1. Sweep anything that expired while the bot was offline
            auto_expire_rentals()

            # 2. Reschedule precise alarms for everything still alive
            active_lines = get_all_active_rentals()
            now = datetime.datetime.now(datetime.timezone.utc)

            for line in active_lines:
                rental_id = line[0]
                exp_time = line[1]
                user_id = line[2]

                # Make sure timezone math matches
                if exp_time.tzinfo is None:
                    exp_time = exp_time.replace(tzinfo=datetime.timezone.utc)

                delay_seconds = (exp_time - now).total_seconds()
                reminder_seconds = delay_seconds - (6 * 3600) # 6 hours before
                
                # Re-arm Alarm 1: 6-Hour Warning
                if reminder_seconds > 0:
                    tg_app.job_queue.run_once(
                        scheduled_6h_reminder,
                        when=reminder_seconds,
                        data={"rental_id": rental_id, "user_id": user_id},
                        name=f"warn_{rental_id}"
                    )
                    
                # Re-arm Alarm 2: The Kill Switch
                if delay_seconds > 0:
                    tg_app.job_queue.run_once(
                        scheduled_expire_rental,
                        when=delay_seconds,
                        data={"rental_id": rental_id, "user_id": user_id},
                        name=f"expire_{rental_id}"
                    )
                    
            logger.info(f"✅ Successfully re-armed {len(active_lines)} rental alarms!")
            
            # 3. ⏰ SCHEDULE THE DAILY CRON JOB (OUTSIDE THE LOOP!)
            # Define the exact time (Midnight UTC)
            #time_to_run = datetime.time(hour=0, minute=0, second=0, tzinfo=datetime.timezone.utc)
            time_to_run = datetime.time(hour=17, minute=59, second=0, tzinfo=datetime.timezone.utc)
            
            # Start the background robot
            tg_app.job_queue.run_daily(
                scheduled_auto_extend_plus_daily_check,
                time=time_to_run,
                name="daily_extension_cron"
            )
            logger.info("✅ Daily 2-Month extension cron scheduled for midnight UTC.")
            # ---------------------------------------------------------
            
            return True
        except Exception as e:
            await notify_admin(f"Telegram not up: {e}")
            logger.exception("Telegram not ready yet: %s", e)
            return False

async def on_error(update, context):
    logger.exception("Unhandled Telegram error", exc_info=context.error)


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
        except Exception as e:
            logger.exception("Failed to notify admin %s for order %s", admin_id, order_code)
            await notify_admin(f"Couldnt notify admin: {e}")


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
        # 🚨 THE TRUTH: Print the exact raw API response to the console!        
        if data.get("status") != "success":
            logger.warning("Plisio invoice details not success: %s", str(data)[:300])
            return None

        inv = (data.get("data") or {}).get("invoice") or {}
        return inv if isinstance(inv, dict) else None
    
    except Exception as e:
        logger.exception("Failed to fetch Plisio invoice details")
        await notify_admin(f"Couldnt fetch Plisio Inv: {e}")
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

    
    if data == "top_up_wallet":
        await open_wallet_menu(update, context)
        return
    
    
    # Ensure BOTH of these triggers lead to the same function
    if data == "other_countries_start" or data == "other_countries_keypad":
        from handlers.global_flow import handle_global_start
        await handle_global_start(update, context)
        return
    
    if data == "otp_rental_universal":
        await handle_rental_universal(update, context)
        return

    # Route OTP/tools/service callbacks into tools_callback
    if data.startswith(("tool_", "otp_", "service_", "esim_" )):
        await tools_callback(update, context)
        return
    
    # ✅ Route the Global Flow callbacks
    if data.startswith("g_"):
                
        if data.startswith("g_type_"):
            await handle_global_type(update, context)
            return
        elif data.startswith("g_dur_"):
            await handle_global_duration(update, context)
            return
        elif data == "g_country_more": # <--- ADD THIS RULE FOR THE TXT FILE
            await handle_other_countries_click(update, context)
            return
        
        elif data.startswith("g_country_"):
            await handle_global_country_selection(update, context)
            return
    

    if data.startswith("manage_rental:"):
        await manage_rental_menu(update, context)
        return
    
    # ✅ ADD THIS: Catches the Check SMS button!
    elif data.startswith("check_sms:"):
        await check_sms_action(update, context)
        return

    elif data == "my_rentals_back":
        await my_rentals_menu(update, context)
        return
    
    elif data == "admin_check_balance":
        await admin_check_balance(update,context)
        return
    
    elif data == "admin_stats":
        await admin_get_stats(update, context)
        return
    
    if data.startswith("extend_rental:"):
        await trigger_extension_menu(update, context)
        return
    

    
    await delete_tracked_message(context, q.message.chat_id, "pending_prompt_msg_id")

    data = (q.data or "").strip()
    user_id = q.from_user.id

    # Back to main (everyone)
    if q.data == "back_main":
        # The user clicked "❌ Close"
        try:
            await q.message.delete()
        except Exception:
            pass
        return
    
    if data.startswith("wallet_") or data == "back_main":
        return await wallet_callback(update, context)


    # ADMIN list menu + paging (admin.py)
    if data == "admin_menu" or data.startswith("admin_paid:") or data.startswith("admin_delivered:") or data.startswith("admin_open_paid:") or data.startswith("admin_rental_"):
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
    
    # 📢 BROADCAST ALL TRIGGER
    if data == "admin_broadcast_all":
        if not _is_admin(user_id): return
        context.user_data["admin_step"] = "awaiting_broadcast_all"
        await q.message.reply_text(
            "📢 <b>Mass Broadcast Mode</b>\n\n"
            "Send the message you want to deliver to ALL users.\n"
            "Type <code>cancel</code> to exit.",
            parse_mode="HTML"
        )
        await q.answer()
        return

    # 👤 SINGLE USER MESSAGE TRIGGER
    if data == "admin_broadcast_single":
        if not _is_admin(user_id): return
        context.user_data["admin_step"] = "awaiting_broadcast_user_id"
        await q.message.reply_text(
            "👤 <b>Direct Message Mode</b>\n\n"
            "Please send the <b>User ID</b> of the person you want to message.",
            parse_mode="HTML"
        )
        await q.answer()
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
        or data == "social_menu"
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


     
async def force_expire_order_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Manually triggers the silent expiration logic for testing.
    Usage: /force_expire_order ORD-XXXXX
    """
    if not _is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("❌ Usage: /force_expire_order ORD-XXXXX")
        return

    order_number = context.args[0].strip()
    order = get_order_by_code(order_number)

    if not order:
        await update.message.reply_text(f"❌ Order {order_number} not found in database.")
        return

    # 1. Update the Database exactly like the webhook does
    try:
        update_payment_status_by_order_code(order_number, pay_status="expired")
        if order.get("id"):
            update_order_status(order["id"], "expired")
        
        # 2. Log it so you can verify it worked
        logger.info(f"TEST: Order {order_number} manually expired. (No notification sent).")
        
        await update.message.reply_text(
            f"✅ <b>Success:</b> {order_number} is now marked as 'expired' in the DB.\n\n"
            f"The user received <b>no notification</b>, which is correct.",
            parse_mode="HTML"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to update DB: {e}")
        
# ------------------------------
# TEXT ROUTER
# ------------------------------
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Safety Check: Ensure there is actually a message and text
    if not update.message or not update.message.text:
        return    
    user_id = update.effective_user.id
    text = update.message.text.strip()
    low_text = text.lower()
    
    # 🏁 THE ULTIMATE TRACKER
    logger.info(f"📥 [ROUTER] Incoming from {user_id}: {text[:30]}")
    logger.info(f"🧠 [ROUTER] Current Step: {context.user_data.get('admin_step')}")
    
    # 🛑 1. THE GLOBAL INTERCEPTOR 🛑
    # Put your exact button names here in all lowercase
    global_menu_buttons = [
        "🧰 tools", "🛒 orders", "💰 credit", "🛠 support",
        "🇺🇸 purchase usa number", "🌍 purchase non number"
                           
    ] 
    
    if any(k in low_text for k in global_menu_buttons):
        await delete_tracked_message(context, update.effective_chat.id, "otp_instruction_msg_id")
        # Instantly wipe EVERY process they were stuck in (Rental, OTP, Wallet, Admin, etc.)
        trap_doors = [
            "otp_step", 
            "wallet_step", 
            "msn_step", 
            "esim_step", 
            "awaiting_extension_choice"
        ]
        for trap in trap_doors:
            context.user_data.pop(trap, None)
            

    # 🛠 2. FUZZY SUPPORT MATCH
    if "support" in low_text:
        return await help_cmd(update, context)
            

    # 👇 ... The rest of your normal routing logic continues down here ... 👇
    step = context.user_data.get("otp_step")
    
    # If they clicked "🧰 Tools", 'step' is now None, so it safely skips this rental block!
    if step == "rental_final_confirm":
        await confirm_rental(update, context)
        return  # Stop here if they are in the rental flow
        
    if await handle_otp_text_input(update, context):
        asyncio.create_task(safe_delete_user_message(update))
        return
        
    # 🛑 3. THE EXTENSION INTERCEPTOR 🛑
    if context.user_data.get("awaiting_extension_choice"):
        await handle_extension_text(update, context)
        asyncio.create_task(safe_delete_user_message(update))
        return

    # Admin wizard capture FIRST
    if await _admin_capture_text(update, context):
        asyncio.create_task(safe_delete_user_message(update))
        return
    
    # Wallet flow
    if context.user_data.get("wallet_step"):
        await delete_tracked_message(context, update.effective_chat.id, "otp_instruction_msg_id")
        
        if await handle_wallet_text_input(update, context):
            asyncio.create_task(safe_delete_user_message(update))
            return
        
        #Other Country Flow
        
     # Inside text_router in bot.py:
    
    # 🌍 THE GLOBAL COUNTRY ID INTERCEPTOR 
    if context.user_data.get("otp_step") == "awaiting_global_country_id":        
        # 1. Start the vaporize timer so their typed number disappears
        asyncio.create_task(safe_delete_user_message(update))
        
        # 2. Check if they actually typed a number
        if not text.isdigit():
            msg = await update.message.reply_text("❌ Please enter a valid numeric ID (e.g., 73).")
            # Cleanup the warning after 4 seconds
            async def cleanup_warning():
                await asyncio.sleep(4)
                try: await msg.delete()
                except: pass
            asyncio.create_task(cleanup_warning())
            return
            
        # 3. Save the ID and clear the trap
        context.user_data['is_global_flow'] = True
        context.user_data['global_country_id'] = text
        context.user_data.pop("otp_step", None) # Clear the text trap
        
        # 4. Trigger the exact same loading screen that China/UK get
        loading_msg = await update.message.reply_text("🔄 **Connecting to global servers and fetching live prices... Please wait.**", parse_mode="Markdown")
        
        # 5. ---> STAGE 2, PHASE B (The Fetch) WILL GO HERE <---
        await asyncio.sleep(1.5)
        await loading_msg.edit_text(f"✅ Data fetched for Typed Country ID {text}!\n\n(Service list integration coming next...)")
        return   
    
    
    # 🌍 THE GLOBAL COUNTRY ID INTERCEPTOR
    if context.user_data.get("otp_step") == "awaiting_global_country_id":
        await process_global_country_input(update, context, text)
        return
        
    # --- RENTAL FLOW ---
    # Rental Product ID Step
    if context.user_data.get("otp_step") == "awaiting_rental_product_id":
        # Delegate to your rental handler for processing
        await handle_rental_product_id(update, context)
        asyncio.create_task(safe_delete_user_message(update))
        return
            
    # THE RENTAL BUTTON INTERCEPTOR
    if step == "awaiting_rental_button":
        # Starts the 10-sec user delete in the background (Zero lag!)
        asyncio.create_task(safe_delete_user_message(update)) 
        await resend_rental_menu(update, context) 
        return
        
    # THE ONE-TIME OTP BUTTON INTERCEPTOR
    if step == "awaiting_otp_button":
        # Starts the 10-sec user delete in the background (Zero lag!)
        asyncio.create_task(safe_delete_user_message(update))
        await resend_otp_menu(update, context)
        return
    
    # Handle the state selection step for rental
    if context.user_data.get("otp_step") == "awaiting_state":
        # Ask for the state after validating product ID
        await handle_rental_state(update, context)
        asyncio.create_task(safe_delete_user_message(update))
        return
    
    if context.user_data.get("otp_step") == "awaiting_state_or_random":
        await handle_state_or_random(update, context)
        asyncio.create_task(safe_delete_user_message(update))
        return

    # --- MAIN KEYPAD ROUTING ---
    user_id = update.effective_user.id

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
    if any(k in low_text for k in ["tools", "orders", "credit", "support", "purchase usa number", "purchase non number"]):
        
        asyncio.create_task(safe_delete_user_message(update))
        
        # MEMORY TRACKER
        if "purchase usa number" in low_text: context.user_data["current_menu"] = "usa_number"
        elif "purchase non number" in low_text: context.user_data["current_menu"] = "other_number"
        if "tools" in low_text: context.user_data["current_menu"] = "tools"
        elif "orders" in low_text: context.user_data["current_menu"] = "orders"
        elif "credit" in low_text: context.user_data["current_menu"] = "wallet"
        elif "support" in low_text: context.user_data["current_menu"] = "support"
        
        # clear OTP step so it doesn't hijack menu navigation
        context.user_data.pop("otp_step", None)
        context.user_data.pop("wallet_step", None)
        pending = None  # prevent UnboundLocalError no matter what
                    
        if "credit" in low_text:
               await open_wallet_menu(update, context)
               return
           
           
        if "purchase non number" in low_text: 
            context.user_data["current_menu"] = "other_number"
            # ✅ CALL THE UNIFIED HANDLER
            from handlers.global_flow import handle_global_start
            await handle_global_start(update, context)

        # if Tools clicked and there is a pending order, redirect to pending page
        if "tools" in low_text:
            pending = expire_pending_order_if_needed(user_id)

        if pending and pending.get("status") == "pending":
            pay_status = (pending.get("pay_status") or "").lower().strip()
            if pay_status in {"pending", "", "new"}:
                await delete_tracked_message(
                    context,
                    update.effective_chat.id,
                    "pending_prompt_msg_id",
                )

                msg = await safe_send(
                    update,
                    context,
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

    # --- FALLBACK FLOWS ---
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

   
        
    # 🚨 THE SMART CONTEXT-AWARE SAFETY NET (V7 - NO-AMNESIA FIX) 🚨
    warning_msg = await update.message.reply_text(
        "⚠️ <b>Invalid input. Please use the menu buttons above.</b>", 
        parse_mode="HTML"
    )
    

    # 📢 BROADCAST ALL LOGIC (with 24h Auto-Delete)
    if context.user_data.get("admin_step") == "awaiting_broadcast_all":
        if update.effective_user.id not in ADMIN_IDS: return
        # 1. ESCAPE THE INPUT FIRST
        safe_text = escape(text)
        
        broadcast_text = f"📢 <b>ANNOUNCEMENT FROM UNDERGROUND BOX</b>\n\n{safe_text}"
        all_users = get_all_user_ids() 
        logger.info(f"🚀 Starting Broadcast to {len(all_users)} users.")
        
        success_count = 0
        for uid in all_users:
            try:
                sent_msg = await context.bot.send_message(
                    chat_id=uid,
                    text=broadcast_text, 
                    parse_mode="HTML",
                    disable_web_page_preview=True
                    )
                success_count += 1
                
                # 🕒 Schedule deletion after 24 hours (86400 seconds)
                context.job_queue.run_once(
                    _delete_message_later,
                    when=24 * 3600,
                    data={"chat_id": uid, "message_id": sent_msg.message_id},
                    name=f"mass_del_{uid}_{sent_msg.message_id}"
                )
                
                await asyncio.sleep(0.05) # Prevent Telegram flood limits
            except: continue
            
        await update.message.reply_text(f"✅ Broadcast complete! Delivered to {success_count} users and scheduled for 24h deletion.")
        context.user_data.pop("admin_step", None)
        return

    # 👤 SINGLE USER DIRECT MESSAGE (with 24h Auto-Delete)
    if context.user_data.get("admin_step") == "awaiting_broadcast_user_id":
        if update.effective_user.id not in ADMIN_IDS: return
        if not text.isdigit():
            await update.message.reply_text("❌ Please enter a valid numeric User ID.")
            return
            
        context.user_data["target_broadcast_id"] = int(text)
        context.user_data["admin_step"] = "awaiting_broadcast_single_text"
        await update.message.reply_text(f"🎯 Target ID: `{text}`\n\nNow send the message you want to deliver.")
        return
    

    if context.user_data.get("admin_step") == "awaiting_broadcast_single_text":
        if update.effective_user.id not in ADMIN_IDS: return
        target_id = context.user_data.get("target_broadcast_id")
        safe_text = escape(text)
        
        # 🟢 DEBUG LOGS: See what the bot is trying to do
        logger.info(f"🔍 DEBUG: Attempting single-user message.")
        logger.info(f"🎯 Target ID: {target_id} | Message: {text[:20]}...")
        
        
        try:
            sent_msg = await context.bot.send_message(
                chat_id=target_id, 
                text=f"✉️ <b>Message from Support</b>\n\n{safe_text}", 
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            
            logger.info(f"✅ DEBUG: Message successfully sent to {target_id}")
            
            # 🕒 Schedule deletion after 24 hours
            context.job_queue.run_once(
                _delete_message_later,
                when=24 * 3600,
                data={"chat_id": target_id, "message_id": sent_msg.message_id},
                name=f"single_del_{target_id}_{sent_msg.message_id}"
            )
            
            await update.message.reply_text(f"✅ Message sent to {target_id} and scheduled for deletion in 24h.")
        except Exception as e:
            # and the EXACT line where it died.
            logger.error("🛑 CRITICAL FAILURE DETAILS:")
            logger.error(traceback.format_exc())
            logger.error(f"❌ DEBUG ERROR: Failed to send to {target_id}. Error: {e}")
            await update.message.reply_text(f"❌ Delivery failed: {e}")
            
        context.user_data.pop("admin_step", None)
        context.user_data.pop("target_broadcast_id", None)
        return
    
    
    # Vaporize their rubbish and the warning after 4 seconds
    async def cleanup_rubbish():
        await asyncio.sleep(4)
        try:
            await warning_msg.delete()
        except Exception:
            pass
        try:
            await update.message.delete()
        except Exception:
            pass
            
    asyncio.create_task(cleanup_rubbish())
    return

    
# ------------------------------
# /admin wrapper
# ------------------------------

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Catches any unregistered or unauthorized commands."""
    # 1. Instantly delete the wrong command they typed (e.g., /rubbish)
    asyncio.create_task(safe_delete_user_message(update))

    # 2. Send the warning WITHOUT attaching the keypad!
    warning_msg = await safe_send(
        update,
        context,
        f"❌ <b>Wrong Command.</b>\n\n🛠 Need help? Contact {SUPPORT_HANDLE}",
        parse_mode="HTML"
        # ❌ Notice there is no reply_markup here. The 4-dots are safe!
    )
    
    # 3. Save it to the Janitor so it gets wiped the moment they click any other button
    if warning_msg:
        context.user_data["otp_instruction_msg_id"] = warning_msg.message_id
                
    
async def admin_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await admin_command(update, context, ADMIN_IDS)

# ------------------------------
# REGISTER HANDLERS
# ------------------------------
tg_app = ApplicationBuilder().token(BOT_TOKEN).request(tg_request).build()
tg_app.add_handler(CommandHandler("start", start))
tg_app.add_handler(CommandHandler("admin", admin_entry))
tg_app.add_handler(CommandHandler("debug_last_order", debug_last_order))
tg_app.add_handler(CommandHandler("debug_payload", debug_payload))
tg_app.add_handler(CallbackQueryHandler(callback_router))
tg_app.add_handler(CommandHandler("rescue", rescue_my_number))
tg_app.add_handler(CommandHandler("rentals", my_rentals_menu))
tg_app.add_handler(CallbackQueryHandler(manage_rental_menu, pattern="^manage_rental:"))
tg_app.add_handler(CallbackQueryHandler(my_rentals_menu, pattern="^my_rentals_back$"))
tg_app.add_error_handler(global_error_handler)
tg_app.add_error_handler(on_error)
tg_app.add_handler(CommandHandler("test_extend", force_test_auto_extend))
tg_app.add_handler(CommandHandler("test_warn", test_6h_warning))
tg_app.add_handler(CommandHandler("test_expire", test_expire_alarm))
tg_app.add_handler(CallbackQueryHandler(admin_check_balance, pattern="^admin_check_balance$"))
tg_app.add_handler(CommandHandler("force_expire_order", force_expire_order_test))
# ... inside your handler registration ...
tg_app.add_handler(CallbackQueryHandler(handle_global_start, pattern="^other_countries_start$"))
tg_app.add_handler(CallbackQueryHandler(handle_global_type, pattern="^g_type_"))
tg_app.add_handler(CallbackQueryHandler(handle_global_duration, pattern="^g_dur_"))
# Matches g_country_3 and g_country_15, but ignores g_country_more for now
tg_app.add_handler(CallbackQueryHandler(handle_global_country_selection, pattern="^g_country_\\d+$"))
register_side_menu(tg_app)



# IMPORTANT: media before text (QR upload wizard)
# First: OTP text handler
tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router), group=0)
# Lastly: Your media router
tg_app.add_handler(MessageHandler((filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND, media_router))

tg_app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

TG_READY = False
TG_LOCK = asyncio.Lock()


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
                await notify_admin(f"Webhook Setting failed {e}")
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



# PLISIO WEBHOOK
# ------------------------------
async def plisio_webhook(req: Request):
    ctype = (req.headers.get("content-type") or "").lower()

    # ---------------------------
    # Parse payload (json or form)
    # ---------------------------
    try:
        if "multipart/form-data" in ctype or "application/x-www-form-urlencoded" in ctype:
            form = await req.form()
            payload = dict(form)
        else:
            payload = await req.json()
    except Exception:
        body = await req.body()
        logger.warning(
            "PLISIO WEBHOOK: parse failed content-type=%s body=%r",
            ctype,
            body[:500],
        )
        return {"ok": True}

    # Some providers nest under {"data": {...}}
    p = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
    if not isinstance(p, dict):
        return {"ok": True}

    # ---------------------------
    # Extract important fields
    # ---------------------------
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

    is_paid = status in paid_statuses
    is_expired = status in expired_statuses

    # Wallet topup flag (define ONCE)
    desc_raw = (order.get("description") or "")
    is_wallet_topup = bool(order) and (
        order.get("order_type") == "wallet_topup"
        or desc_raw.upper().startswith("WALLET_TOPUP:")
    )
    
    logger.info(
        "WEBHOOK order=%s type=%r desc=%r is_wallet_topup=%s wallet_credited=%r",
        order_number,
        order.get("order_type"),
        order.get("description"),
        is_wallet_topup,
        order.get("wallet_credited"),
    )

    # ---------------------------
    # 🚨 SECURITY LOCK: Verify directly with Plisio
    # ---------------------------
    if not txn_id:
        return {"ok": True}

    # We completely ignore the webhook's fake payload and ask Plisio for the truth
    inv = await _fetch_plisio_invoice_details(txn_id.strip())
    if not inv:
        logger.error(f"🚨 SECURITY ALERT: Fake webhook blocked! txn_id {txn_id} not found on Plisio.")
        return {"ok": True}

    # Override the untrusted webhook status with the REAL status from Plisio's servers
    status = (inv.get("status") or p.get("status") or "").lower().strip()
    
    paid_statuses = {"paid", "completed", "success", "confirmed", "finish", "finished"}
    expired_statuses = {"expired", "cancelled", "canceled", "failed", "error"}

    is_paid = status in paid_statuses
    is_expired = status in expired_statuses

    # Detect real payment activity from the verified invoice
    detected_now = False
    invoice_received = _to_float(inv.get("received_amount") or 0)
    
    status = (inv.get("status") or "").lower().strip()
    # In Plisio API, 'pending' status means crypto is officially on the blockchain unconfirmed
    if status == "pending" or invoice_received > 0:
        detected_now = True

    
    # EXPIRED / FAILED (highest priority)
    # ---------------------------
    if is_expired:
        # 1. Check if the order is already marked dead in our DB
        if current_pay_status in {"expired", "cancelled", "canceled"}:
            logger.info(f"Ignoring Plisio timeout for already dead order: {order_number}")
            return {"ok": True}
        
        # 2. Update the Database so the order is no longer "Pending"
        try:
            update_payment_status_by_order_code(order_number, pay_status="expired", pay_txn_id=txn_id)
            if order.get("id"):
                update_order_status(order["id"], "expired")
            logger.info(f"Order {order_number} marked as expired in DB (No notification sent to user).")
        except Exception as e:
            logger.exception("update_payment_status_by_order_code(expired) failed")
            await notify_admin(f"update_payment_status Failed: {e}")

        return {"ok": True}
    
    # ---------------------------
    # DETECTED or PAID
    # ---------------------------
    if detected_now or is_paid:
        new_pay_status = "paid" if is_paid else "detected"
        first_time = current_pay_status not in {"detected", "paid"}

        # Update pay_status (idempotent)
        try:
            if current_pay_status != new_pay_status:
                update_payment_status_by_order_code(order_number, pay_status=new_pay_status, pay_txn_id=txn_id)
        except Exception as e:
            logger.exception("update_payment_status_by_order_code(%s) failed (ignored)", new_pay_status)
            await notify_admin(f"update_payment_status Failed: {e}")

        # Move order into processing (idempotent)
        try:
            if order.get("id"):
                update_order_status(order["id"], "processing")
        except Exception as e:
            logger.exception("update_order_status(processing) failed (ignored)")
            await notify_admin(f"update_payment_status failed: {e}")
            

        # ✅ CREDIT WALLET ON DETECTED/PAID (RATIO MATH FIX + PENDING CHECK)
        if is_wallet_topup and order and not order.get("wallet_credited"):
            usd_actual_received = 0.0
            fiat_exp = 0.0  
            crypto_received = "0.0"
            currency = "CRYPTO"
            tx_url = "#"

            try:
                # 1. PULL THE TRUTH FROM THE TX LIST (UNCONFIRMED FUNDS)
                c_rec = 0.0
                tx_list = inv.get("tx") or []
                
                # We check the 'tx' list first because it shows unconfirmed SOL/Crypto
                if isinstance(tx_list, list) and len(tx_list) > 0:
                    for t in tx_list:
                        c_rec += _to_float(t.get("value") or 0)
                
                # Fallback to standard fields only if tx list is empty
                if c_rec <= 0:
                    c_rec = _to_float(inv.get("received_amount") or p.get("received_amount") or 0.0)

                c_exp = _to_float(inv.get("amount") or p.get("amount") or 1.0)
                # Ensure we have the original USD amount from DB or Plisio
                fiat_exp = _to_float(inv.get("source_amount") or p.get("source_amount") or order.get("amount_usd") or 0.0)
                
                crypto_received = str(c_rec)
                currency = inv.get("currency") or p.get("currency") or "CRYPTO"
                
                # Handle tx_url being a list (common for Solana/SOL)
                raw_url = inv.get("tx_url") or p.get("tx_url")
                if isinstance(raw_url, list) and len(raw_url) > 0:
                    tx_url = raw_url[0]
                else:
                    tx_url = raw_url or f"https://plisio.net/invoice/{txn_id}"

                # 2. DO THE MATH (Ratio: Received / Expected * USD Price)
                if c_rec > 0 and c_exp > 0:
                    usd_actual_received = (c_rec / c_exp) * fiat_exp
                    
                logger.info(f"✅ MATH SUCCESS | Expected: {c_exp} | Received: {c_rec} | Crediting: ${usd_actual_received}")

            except Exception as e:
                logger.error(f"❌ Error during ratio math: {e}")
                usd_actual_received = 0.0

            # 3. Credit if the math proves funds actually arrived
            if usd_actual_received > 0:
                try:
                    add_user_balance_usd(order["user_id"], float(usd_actual_received))
                    mark_order_wallet_credited(order_number)
                    
                    # ✅ DETECT PARTIAL PAYMENT
                    is_partial = False
                    if fiat_exp > 0 and usd_actual_received < (fiat_exp - 0.02):
                        is_partial = True
                        
                    # ✅ REWRITE DB HISTORY & FLAG PARTIAL
                    update_order_actual_amount(order_number, usd_actual_received, is_partial)
                    
                    # Save it to memory so the Admin Notifier can see it!
                    order["credited_amount"] = usd_actual_received
                    
                    # Update status to completed immediately 
                    update_payment_status_by_order_code(order_number, pay_status="paid", pay_txn_id=txn_id)
                    if order.get("id"):
                        update_order_status(order["id"], "completed")

                    # 4. SUCCESS MESSAGE WITH BLOCKCHAIN TRUTH & UNDERPAYMENT ALERT
                    if await ensure_telegram_ready():
                        new_bal = get_user_balance_usd(order["user_id"])
                        
                        msg_text = f"✅ <b>Wallet Credited: +${float(usd_actual_received):.2f}</b>\n\n"
                        
                        # 🚨 THE NEW UNDERPAYMENT ALERT 🚨
                        if fiat_exp > 0 and usd_actual_received < (fiat_exp - 0.02):
                            msg_text += (
                                f"⚠️ <b>PARTIAL PAYMENT DETECTED</b>\n"
                                f"<b>Invoice Expected:</b> ${fiat_exp:.2f}\n"
                                f"<b>Actually Paid:</b> ${usd_actual_received:.2f}\n"
                                f"<i>(You were credited for exactly what arrived on the blockchain)</i>\n\n"
                            )
                        
                        msg_text += (
                            f"💵 <b>Amount Received:</b> ${float(usd_actual_received):.2f}\n"
                            f"🪙 <b>Blockchain Value:</b> {crypto_received} {currency}\n"
                            f"🔗 <b>Transaction:</b> <a href='{tx_url}'>View on Explorer</a>\n\n"
                            f"💰 <b>New Total Balance:</b> ${new_bal:.2f}"
                        )
                        
                        sent_wallet_msg = await tg_app.bot.send_message(
                            chat_id=order["user_id"], 
                            text=msg_text,
                            parse_mode="HTML",
                            disable_web_page_preview=True
                        ) 
                         
                        tg_app.job_queue.run_once(
                            _delete_message_later,
                            when=3600,
                            data={"chat_id": order["user_id"], "message_id": sent_wallet_msg.message_id}
                        )
                except Exception as e:
                    logger.exception(f"Wallet credit failed: {e}")
                    await notify_admin(f"Wallet credit failed for {order_number}: {e}")

        # Notify admin/user only on first transition to detected/paid
        if first_time:
            try:
                if await ensure_telegram_ready():
                    # ✅ Inject the actual credited amount into the Admin's notification on a new line!
                    if order.get("credited_amount"):
                        original_desc = order.get("description") or "Wallet Top Up"
                        order["description"] = f"{original_desc}\n💵 Actual Credited: ${order['credited_amount']:.2f}"
                        
                    asyncio.create_task(_notify_admin_new_paid_order(order))
            except Exception as e:
                logger.exception("Admin notify failed (ignored)")
                await notify_admin(f"Couldnt Notify Admin : {e}")

            if chat_id and await ensure_telegram_ready():
                det_text = (
                    f"✅ Payment detected for order {order_number}. "
                    "Kindly wait while your order is being fulfilled.\n\n"
                )
                
                sent_det_msg = await tg_app.bot.send_message(chat_id=chat_id, text=det_text)
                
                tg_app.job_queue.run_once(
                    _delete_message_later,
                    when=3600,
                    data={"chat_id": chat_id, "message_id": sent_det_msg.message_id}
                )

                # Optional eSIM processing notice
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

    # ---------------------------
    # Ignore noisy repeats after detected/paid
    # ---------------------------
    if current_pay_status in {"detected", "paid"}:
        return {"ok": True}

    # ---------------------------
    # Otherwise: store whatever status we got
    # ---------------------------
    try:
        update_payment_status_by_order_code(order_number, pay_status=status or "pending", pay_txn_id=txn_id)
    except Exception as e:
        logger.exception("update_payment_status_by_order_code(%s) failed (ignored)", status or "pending")
        await notify_admin(f"update_payment_status_by_order_code Failed: {e}")

    return {"ok": True}


        

# Don't forget to register it with your handlers!
tg_app.add_handler(CommandHandler("fixdb", fix_db_sequence))




@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/webhooks/plisio")
async def plisio_webhook_post(req: Request):
    return await plisio_webhook(req)




'''
def _log_task_result(task):
    """Helper to catch any errors if the background fetch fails"""
    try:
        task.result()
    except Exception as e:
        logger.error(f"Background task failed: {e}")
'''

@app.on_event("startup")
async def on_startup():
    print("Fast API up")

    # 1. Create all databases
    create_tables()
    create_service_fetch_status_table()
    create_wallet_transactions_table()

    # ✅ 2. START THE DOUBLE FETCH IN THE BACKGROUND
    # Using asyncio.to_thread prevents the bot from freezing while it downloads the massive lists
    #fetch_task = asyncio.create_task(asyncio.to_thread(fetch_and_save_services))
    #fetch_task.add_done_callback(_log_task_result)

    # 3. Start telegram bootstrap
    asyncio.create_task(_background_telegram_bootstrap())
    
    # ✅ START TELEGRAM BOOTSTRAP FOR SUPPORT BOT
    asyncio.create_task(run_support_bot())