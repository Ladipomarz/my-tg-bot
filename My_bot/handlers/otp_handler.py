from textverified import TextVerified, NumberType, ReservationType, ReservationCapability
import os
import re
import asyncio
from handlers.provider_factory import get_otp_provider
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from io import BytesIO
from telegram import InputFile
from utils.db import build_services_txt_bytes
from utils.db import get_services_for_export, get_service_name_by_code
from utils.auto_delete import safe_send,safe_delete_user_message
from utils.validator import normalize_us_state_full_name
import datetime
from typing import Optional
from telegram.constants import ParseMode
from telegram.ext import CommandHandler
from pricelist import get_otp_price_usd
from utils.db import get_user_balance_usd, try_debit_user_balance_usd, add_user_balance_usd 
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)




API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")




async def otp_verification_handler(update: Update, context: CallbackContext, method: str):
    # Show buttons for choosing between USA and Other Countries
    keyboard = [
        [
            InlineKeyboardButton("🇺🇸 USA", callback_data="otp_usa"),
            InlineKeyboardButton("🌍 Other Countries", callback_data="otp_other_country")
        ],
        [InlineKeyboardButton("⬅ Back", callback_data="otp_back_verification")]
    ]
    await _edit(update, "Please choose your region:", keyboard)



async def show_usa_verification_menu(update: Update, context: CallbackContext):
    # Show buttons for choosing between Text and Voice verification
    keyboard = [
        [
            InlineKeyboardButton("Text Verification", callback_data="tool_otp_usa_text"),
            InlineKeyboardButton("Voice Verification (Coming Soon)", callback_data="tool_otp_usa_voice")
        ],
        [InlineKeyboardButton("⬅ Back", callback_data="otp_back_verification")],  # Back button to the OTP menu
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await update.callback_query.edit_message_text(
            "Please choose the verification method:", 
            reply_markup=reply_markup
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return
        raise  # Reraise if any other error happens  


# Initialize TextVerified client
provider = TextVerified(api_key=API_KEY, api_username=API_USERNAME)
OTP_POLL_INTERVAL_SEC = 5
OTP_REFUND_AFTER_SEC = 5 * 60   # 5 minutes
OTP_INCOMING_TIMEOUT_SEC = 4    # keep < interval to avoid overlap


def _job_name(prefix: str, user_id: int) -> str:
    return f"{prefix}_{user_id}"


def _remove_jobs_by_name(job_queue, name: str) -> None:
    if not job_queue:
        return
    for j in job_queue.get_jobs_by_name(name):
        j.schedule_removal()


async def _cleanup_otp_state(context: ContextTypes.DEFAULT_TYPE, user_id: int | None = None) -> None:
    keys = (
        "otp_step",
        "otp_service_name",
        "otp_state",
        "otp_custom_service",
        "otp_api_service_name",
        "otp_price",
        "otp_random_price",
        "otp_specific_price",
        "otp_verification_id",
        "otp_reserved_number",
        "otp_reserved_at_utc",
        "otp_service_display",
        "otp_poll_job_name",
        "otp_refund_job_name",
        "otp_debited_amount",
    )

    # ✅ Try clearing chat-scoped user_data ONLY if it's a real dict
    try:
        ud = getattr(context, "user_data", None)
        if isinstance(ud, dict):
            for k in keys:
                ud.pop(k, None)
    except Exception:
        pass

    # ✅ Best-effort clear application user_data ONLY if it's mutable dict-of-dicts
    try:
        if user_id is not None:
            app_ud = getattr(context.application, "user_data", None)
            bucket = app_ud.get(user_id) if app_ud else None
            if isinstance(bucket, dict):
                for k in keys:
                    bucket.pop(k, None)
    except Exception:
        pass



# Correcting how the reserve_number_for_otp should handle country and service_name
async def reserve_number_for_otp(service_name: str, country="USA"):
    provider = get_otp_provider(api_key=API_KEY)  # Ensure you're using the correct API key
    # Now reserve the number using both service_name and country if necessary
    number = provider.reserve_number(service_name=service_name, country=country)
    return number


from handlers.servicelist import fetch_and_save_services  # Ensure correct import path

# ---------- OTP MENUS ----------

async def otp_usa_one_time_or_rental_menu(update, context, method: str):
    keyboard = [
        [
            InlineKeyboardButton(
                "One-Time",
                callback_data=f"otp_usa_{method}_one_time",
            ),
            InlineKeyboardButton(
                "Rental",
                callback_data=f"otp_usa_{method}_rental",
            ),
        ],
        [InlineKeyboardButton("⬅ Back", callback_data="otp_back_usa_verif_type")],
    ]
    await _edit(update, "Choose rental type:", keyboard)


async def otp_usa_rental_type_menu(update, context, method: str):
    keyboard = [
        [
            InlineKeyboardButton(
                "Monthly Rental",
                callback_data=f"otp_usa_{method}_rental_monthly",
            ),
            InlineKeyboardButton(
                "Forever Rental",
                callback_data=f"otp_usa_{method}_rental_forever",
            ),
        ],
        [InlineKeyboardButton("⬅ Back", callback_data="otp_back_usa_one_time_rental")],
    ]
    await _edit(update, "Choose rental duration:", keyboard)


async def otp_usa_monthly_duration_menu(update, context, method: str):
    keyboard = [
        [
            InlineKeyboardButton(
                "1 Month", callback_data=f"otp_usa_{method}_rental_monthly_1m"
            ),
            InlineKeyboardButton(
                "2 Months", callback_data=f"otp_usa_{method}_rental_monthly_2m"
            ),
        ],
        [
            InlineKeyboardButton(
                "3 Months", callback_data=f"otp_usa_{method}_rental_monthly_3m"
            )
        ],
        [InlineKeyboardButton("⬅ Back", callback_data="otp_back_usa_rental_type")],
    ]
    await _edit(update, "Select duration:", keyboard)
    
    
  
# ---------- INTERNAL HELPER ----------

async def _edit(update, text, keyboard):
    try:
        await update.callback_query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return
        raise


async def send_services_txt(update: Update, context: CallbackContext, *, capability: str = "sms") -> None:
    """
    Fetches the service list, builds the .txt in memory, and sends it to the user.
    """
    # Call the helper to build the txt content
    data_bytes, filename = build_services_txt_bytes(capability=capability)

    # Create a BytesIO object from the data
    bio = BytesIO(data_bytes)
    bio.name = filename  # Telegram uses this as filename

    # Send the file as a document to the user
    await update.callback_query.message.reply_document(
        document=InputFile(bio, filename=filename),
        caption="✅ Here’s the service list.\nReply with the CODE you want.",
        parse_mode="HTML"  # Ensures HTML tags like <b> are properly interpreted

    )
 
async def handle_otp_text_input(update: Update, context: CallbackContext) -> bool:
    """
    Handles OTP flow replies (product id / yes-no / state name / final confirm).
    Returns True if message was handled (so your text_router should stop).
    """
    step = context.user_data.get("otp_step")
    if not step:
        return False

    text = (update.message.text or "").strip()
    low = text.lower()
    
    print(f"[OTP ENTER] step={step!r} text={text!r} user_id={update.effective_user.id}")


    # ---- step: awaiting product id (4 digits) ----
    if step == "awaiting_product_id":
        print(f"User input: {update.message.text}")  # Log the input received
        if not text.isdigit() or len(text) not in (3, 4):  # support old 3-digit and new 4-digit
            await update.message.reply_text("❌ Invalid Product ID. Please reply with the Product ID (e.g. 0123).")
            return True

        service_name = get_service_name_by_code(text)
        if not service_name:
            await update.message.reply_text("❌ I couldn't find that Product ID in the DB. Try again or press Skip.")
            return True

        context.user_data["otp_service_name"] = service_name

        # Ask state preference
        context.user_data["otp_step"] = "ask_specific_state"
        await update.message.reply_text(
            "If you've got the 4-digit Product ID, we can proceed.\n\n"
            "⚠️Please make sure the service is not listed before using the universal phone number.\n\n"
            "Do you want the number to be generated from a specific US state?\n"
            "Reply with: yes / no"
        )
        return True

    # ---- step: ask specific state yes/no ----
    if step == "ask_specific_state":
        print(f"User input: {update.message.text}")  # Log the input received
        if low not in ("yes", "no"):
            await update.message.reply_text("Please reply with: yes or no")
            return True

        # "General Service" (unlisted/universal) uses cheaper pricing.
        is_general = (
            (context.user_data.get("otp_api_service_name") == "servicenotlisted")
            or not context.user_data.get("otp_service_name")
        )

        random_price_val = get_otp_price_usd(is_general_service=is_general, specific_state=False)
        specific_price_val = get_otp_price_usd(is_general_service=is_general, specific_state=True)

        # store for UI + later confirmation
        context.user_data["otp_random_price"] = random_price_val
        context.user_data["otp_specific_price"] = specific_price_val

        random_price = f"${random_price_val:.2f}"
        specific_price = f"${specific_price_val:.2f}"

        
        if low == "yes":
            context.user_data["otp_step"] = "await_state_name"
            print(f"[OTP STEP SET] -> await_state_name (text was {text!r}) user_data={dict(context.user_data)}")

            await update.message.reply_text(
                f"Specific State Price: {specific_price}\n"
                f"Random State Price: {random_price}\n\n"
                "🇺🇸 Which US state do you want the phone number to be generated from?\n"
                "✅ Example: California"
            )
            return True
        
        # If "no" is selected => Set random state and proceed to final confirmation
        context.user_data["otp_state"] = "Random"  # Random state set
        context.user_data["otp_step"] = "final_confirm"  # Proceed to final confirmation step
        await _send_final_confirmation(update, context)  # Send final confirmation message
        return True
    
    # ---- step: awaiting state name (user types state) ----
    # Step: waiting for state name
    if step == "await_state_name":
        state_name = update.message.text.strip()        
        
        if not state_name:
            await update.message.reply_text("❌ Please enter a valid state name (e.g. California).")
            return True

        ok, canon = normalize_us_state_full_name(state_name)
        
        if ok:
            context.user_data["otp_state"] = canon
            context.user_data["otp_step"] = "final_confirm"
            await _send_final_confirmation(update, context)
            return True
        else:
            await update.message.reply_text("❌ Invalid state. Please enter the full state name (e.g. California).")
            return True



    # ---- step: final confirm yes/no ----
        # ---- step: final confirm yes/no ----
    if step == "final_confirm":

        if low not in ("yes", "no"):
            await update.message.reply_text("Please reply with: yes or no")
            return True

        if low == "no":
            # cancel + clear
            for k in ("otp_step", "otp_service_name", "otp_state", "otp_custom_service", "otp_api_service_name"):
                context.user_data.pop(k, None)
            await update.message.reply_text("✅ Cancelled.")
            return True

        # low == "yes"  ✅ everything from here down is YES-only
        selected = context.user_data.get("otp_service_name")          # DB service
        custom = context.user_data.get("otp_custom_service")          # "General Service" from skip
        api_override = context.user_data.get("otp_api_service_name")  # "servicenotlisted" from skip

        display_service = selected or custom or "Custom"
        api_service = api_override or selected or "servicenotlisted"
        service_not_listed_name = display_service if api_service == "servicenotlisted" else None

        state = context.user_data.get("otp_state")  # None => random
        
        
        user_id = update.effective_user.id

        # Price should already be set earlier, but recompute safely if missing
        price_val = context.user_data.get("otp_price")
        if price_val is None:
            is_general = (api_service == "servicenotlisted")
            specific_state = bool(state) and str(state).lower() != "random"
            price_val = get_otp_price_usd(is_general_service=is_general, specific_state=specific_state)
            context.user_data["otp_price"] = float(price_val)
        price_val =float(price_val)   
        
        
        try:
            ver = await reserve_sms_verification(
                service_name=api_service,
                state=state,
                service_not_listed_name=service_not_listed_name,
            )

            number = (
                getattr(ver, "number", None)
                or getattr(ver, "phone_number", None)
                or getattr(ver, "to_value", None)
            )
            verification_id = (
                getattr(ver, "id", None)
                or getattr(ver, "reservation_id", None)
                or getattr(ver, "verification_id", None)
            )
            
            if not verification_id:
                raise RuntimeError("TextVerified did not return verification_id")


            # ✅ Debit wallet (atomic)
            if not try_debit_user_balance_usd(user_id, float(price_val)):
                bal = get_user_balance_usd(user_id)
                kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Top up wallet", callback_data="wallet_menu")],
            
            ])
                await safe_send(
                    update,
                    context,
                    f"❌ Insufficient wallet balance.\n"
                    f"Price: ${float(price_val):.2f}\n"
                    f"Your balance: ${bal:.2f}\n\n"
                    f"Please top up your wallet and try again.",
                    reply_markup=kb,
                )
                return True
                
            # ✅ stop the OTP flow so user isn't stuck in final_confirm
            context.user_data.pop("otp_step", None)
            # Remember debited amount so we can refund on cancel/timeout
            context.user_data["otp_debited_amount"] = float(price_val)
   

            context.user_data["otp_verification_id"] = verification_id
            context.user_data["otp_reserved_number"] = number
            context.user_data["otp_reserved_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            context.user_data["otp_service_display"] = display_service


            intl_num = format_us_international(number)
            local_num = format_us_local(number)

            await update.message.reply_text(
                (
                    "<b>✅ Reserved number!</b>\n\n"
                    f"<b>Service:</b> {display_service}\n\n"
                    f"<b>State:</b> {state or 'Random'}\n\n"
                    f"<b>Number (Intl):</b> {intl_num}\n\n"
                    f"<b>Number (Local):</b> {local_num}\n\n"
                    f"<b>Verification ID:</b> {verification_id}\n\n"
                    "⏳ Waiting for OTP… I’ll auto-check every 5 seconds (up to 5 minutes)."
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=refund_kb(),
            )

            await start_otp_auto_poll(update, context, verification_id)
            
            
        except Exception as e:
            # refund wallet if we already debited
            try:
                amt = context.user_data.get("otp_debited_amount")
                if amt:
                    add_user_balance_usd(user_id, float(amt))
                    context.user_data.pop("otp_debited_amount", None)
            except Exception:
                pass

            await update.message.reply_text(f"❌ Failed to reserve number: {e}")
            return True

        # clear step data but keep verification info
        for k in ("otp_step", "otp_service_name", "otp_state", "otp_custom_service", "otp_api_service_name", "otp_price"):
            context.user_data.pop(k, None)

        return True
    
    return False



US_STATES_EXAMPLE = "California"

async def _send_final_confirmation(update: Update, context: CallbackContext) -> None:
    service_name = context.user_data.get("otp_service_name") or context.user_data.get("otp_custom_service") or "General Service"
    state = context.user_data.get("otp_state")

    is_general = (
        (context.user_data.get("otp_api_service_name") == "servicenotlisted")
        or not context.user_data.get("otp_service_name")
    )

    specific_state = bool(state) and str(state).lower() != "random"
    price_val = get_otp_price_usd(is_general_service=is_general, specific_state=specific_state)
    context.user_data["otp_price"] = price_val
    price = f"${price_val:.2f}"

    msg = (
        "FINAL CONFIRMATION\n\n"
        f"Service: {service_name}\n"
        f"State: {state or 'Random'}\n"
        f"Price: {price}\n\n"
        "⚠️Please reply with either yes or no to confirm."
    )
    await update.message.reply_text(msg)

def refund_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Refund number", callback_data="otp_refund_now")]
    ])


    
    
def format_us_international(raw: str) -> str:
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    # keep last 10 in case it already includes country code
    if len(digits) > 10:
        digits = digits[-10:]
    return f"+1 {digits}"

def format_us_local(raw: str) -> str:
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    if len(digits) > 10:
        digits = digits[-10:]
    if len(digits) != 10:
        return str(raw)
    a, b, c = digits[:3], digits[3:6], digits[6:]
    return f"({a})\u00A0{b}-{c}"  # NBSP keeps spacing nicer in Telegram
    



def _area_codes_for_state(state_full: str) -> list[str]:
    # TextVerified SDK exposes services.area_codes
    # We keep it simple: match by full name (case-insensitive)
    state_full = (state_full or "").strip().lower()
    codes = []
    for ac in provider.services.area_codes():
        # Many SDKs return AreaCode objects; safest is getattr
        st = (getattr(ac, "state", "") or "").strip().lower()
        if st == state_full:
            codes.append(str(getattr(ac, "area_code", "")).strip())
    return [c for c in codes if c.isdigit()]

async def reserve_sms_verification(
    service_name: str,
    state: str | None,
    service_not_listed_name: str | None = None,
):
    """
    Creates an SMS verification and returns the verification object.
    TextVerified SDK does NOT accept `state=...`.
    We map state -> area codes using provider.services.area_codes().
    """
    def _do():
        kwargs = {
            "service_name": service_name,
            "capability": ReservationCapability.SMS,
        }

        # For "not listed" flow
        if service_not_listed_name and service_name == "servicenotlisted":
            kwargs["service_not_listed_name"] = service_not_listed_name

        # Map state -> area codes
        if state:
            acs = _area_codes_for_state(state)
            if acs:
                kwargs["area_code_select_option"] = acs[:15]

        return provider.verifications.create(**kwargs)

    return await asyncio.to_thread(_do)


def _poll_textverified_once(verification_id: str, since_dt: datetime.datetime) -> Optional[dict]:
    """
    Blocking call. Returns dict with OTP info if found, else None.
    """
    # details() gives the Verification object required by sms.incoming()
    ver = provider.verifications.details(verification_id)

    # sms.incoming() returns a generator of messages (polling internally)
    msgs = provider.sms.incoming(
        ver,
        timeout=OTP_INCOMING_TIMEOUT_SEC,
        polling_interval=1.0,
        since=since_dt,
    )

    try:
        msg = next(msgs)
    except StopIteration:
        return None

    return {
        "code": getattr(msg, "parsed_code", None),
        "content": getattr(msg, "sms_content", None),
        "from": getattr(msg, "from_value", None),
    }


async def _otp_poll_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data or {}
    chat_id = data.get("chat_id")
    user_id = data.get("user_id")
    verification_id = data.get("verification_id")
    reserved_at_iso = data.get("reserved_at_utc")

    # NEW: read these from payload (set in start_otp_auto_poll)
    service_display = data.get("service_display") or "Service"
    reserved_number = data.get("reserved_number") or "Unknown"

    if not chat_id or not user_id or not verification_id:
        return

    # Parse reservation timestamp safely
    since_dt = None
    try:
        if isinstance(reserved_at_iso, str):
            since_dt = datetime.datetime.fromisoformat(reserved_at_iso.replace("Z", "+00:00"))
    except Exception:
        since_dt = None

    if since_dt is None:
        since_dt = datetime.datetime.now(datetime.timezone.utc)

    if since_dt.tzinfo is None:
        since_dt = since_dt.replace(tzinfo=datetime.timezone.utc)

    try:
        result = await asyncio.to_thread(_poll_textverified_once, verification_id, since_dt)
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ OTP polling error: {e}")

        poll_name = data.get("poll_job_name")
        refund_name = data.get("refund_job_name")
        if poll_name:
            _remove_jobs_by_name(context.job_queue, poll_name)
        if refund_name:
            _remove_jobs_by_name(context.job_queue, refund_name)

        await _cleanup_otp_state(context.application, user_id)
        return

    if not result:
        return

    code = result.get("code") or "N/A"
    local_num = format_us_local(reserved_number)

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"{service_display} — OTP Received — {local_num}\n\n"
            f"OTP verification code For {service_display} is: <code>{code}</code>"
        ),
        parse_mode="HTML",
    )

    # Stop both jobs and clear state
    poll_name = data.get("poll_job_name")
    refund_name = data.get("refund_job_name")
    if poll_name:
        _remove_jobs_by_name(context.job_queue, poll_name)
    if refund_name:
        _remove_jobs_by_name(context.job_queue, refund_name)

    await _cleanup_otp_state(context.application, user_id)


def _cancel_and_report_blocking(verification_id: str) -> None:
    # best-effort cancel first
    try:
        if hasattr(provider, "verifications") and hasattr(provider.verifications, "cancel"):
            provider.verifications.cancel(verification_id)
    except Exception as e:
        msg = str(e).lower()
        # ✅ harmless: already cancelled/expired/not cancelable
        if "invalid operation" in msg or "400" in msg:
            pass
        else:
            raise

    # best-effort report issue for “no SMS” if supported by SDK
    try:
        if hasattr(provider, "verifications") and hasattr(provider.verifications, "report"):
            provider.verifications.report(verification_id)
    except Exception:
        pass


async def _otp_refund_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data or {}
    chat_id = data.get("chat_id")
    user_id = data.get("user_id")
    verification_id = data.get("verification_id")
    poll_name = data.get("poll_job_name")

    # NEW: amount debited saved in payload
    debited_amount = data.get("debited_amount")  # float or str

    if not chat_id or not user_id or not verification_id:
        return

    # If polling job no longer exists, OTP was received/cancelled already -> no refund
    if poll_name and context.job_queue.get_jobs_by_name(poll_name) == []:
        return

    # stop polling
    if poll_name:
        _remove_jobs_by_name(context.job_queue, poll_name)

    # cancel + report (provider)
    try:
        await asyncio.to_thread(_cancel_and_report_blocking, verification_id)
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Refund attempt failed: {e}")
        await _cleanup_otp_state(context, user_id)
        return

    # ✅ refund wallet if we debited earlier
    refunded_msg = ""
    try:
        amt = float(debited_amount or 0)
        if amt > 0:
            add_user_balance_usd(user_id, amt)
            refunded_msg = f"\n💸 Wallet refunded: ${amt:.2f}"
    except Exception:
        # don't break refund flow if wallet credit fails
        pass

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "⌛ No OTP received within 5 minutes.\n"
            "I cancelled the verification and reported it as 'no SMS' "
            "(refund/credit depends on TextVerified eligibility)."
            + refunded_msg
        ),
    )

    await _cleanup_otp_state(context, user_id)

    
async def start_otp_auto_poll(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    verification_id: str
) -> None:
    """
    Starts repeating poll (every 5s) + a refund watchdog (after OTP_REFUND_AFTER_SEC).
    Uses context.user_data + job payload only (application.user_data is read-only in your runtime).
    """
    if not context.job_queue:
        await update.effective_message.reply_text("❌ JobQueue not available; cannot auto-poll OTP.")
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    reserved_at_iso = context.user_data.get("otp_reserved_at_utc")
    if not reserved_at_iso:
        reserved_at_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        context.user_data["otp_reserved_at_utc"] = reserved_at_iso

    poll_name = _job_name("otp_poll", user_id)
    refund_name = _job_name("otp_refund", user_id)

    # remove any previous jobs for this user
    _remove_jobs_by_name(context.job_queue, poll_name)
    _remove_jobs_by_name(context.job_queue, refund_name)

    payload = {
        "chat_id": chat_id,
        "user_id": user_id,
        "verification_id": str(verification_id),
        "reserved_at_utc": reserved_at_iso,
        "poll_job_name": poll_name,
        "refund_job_name": refund_name,
        "service_display": context.user_data.get("otp_service_display") or "Service",
        "reserved_number": context.user_data.get("otp_reserved_number") or "Unknown",
        "debited_amount": float(context.user_data.get("otp_debited_amount") or 0),

    }

    # store in context.user_data (safe in your runtime)
    context.user_data["otp_poll_job_name"] = poll_name
    context.user_data["otp_refund_job_name"] = refund_name
    context.user_data["otp_verification_id"] = str(verification_id)
    context.user_data["otp_reserved_at_utc"] = reserved_at_iso
    context.user_data["otp_chat_id"] = chat_id

    context.job_queue.run_repeating(
        _otp_poll_job,
        interval=OTP_POLL_INTERVAL_SEC,
        first=0,
        name=poll_name,
        data=payload,
    )

    context.job_queue.run_once(
        _otp_refund_job,
        when=OTP_REFUND_AFTER_SEC,
        name=refund_name,
        data=payload,
    )
    

    
async def otp_refund_now_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    User pressed "Refund now".
    Stops jobs, cancels + reports on provider, then refunds wallet if we previously debited.
    """
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id
    chat_id = q.message.chat_id

    # Use ONLY context.user_data (application.user_data is read-only in your runtime)
    verification_id = context.user_data.get("otp_verification_id")
    poll_name = context.user_data.get("otp_poll_job_name")
    refund_name = context.user_data.get("otp_refund_job_name")

    if not verification_id:
        await q.message.reply_text("❌ No active verification to refund.")
        return

    # Stop jobs
    if poll_name and context.job_queue:
        _remove_jobs_by_name(context.job_queue, poll_name)
    if refund_name and context.job_queue:
        _remove_jobs_by_name(context.job_queue, refund_name)

    # Cancel + report on provider (best-effort)
    try:
        await asyncio.to_thread(_cancel_and_report_blocking, verification_id)
    except Exception as e:
        await q.message.reply_text(f"❌ Refund attempt failed: {e}")
        await _cleanup_otp_state(context.application, user_id)
        return

    # Refund wallet if we debited earlier
    refunded_msg = ""
    try:
        amt = context.user_data.get("otp_debited_amount")
        if amt is not None:
            amt_f = float(amt)
            if amt_f > 0:
                add_user_balance_usd(user_id, amt_f)
                context.user_data.pop("otp_debited_amount", None)
                refunded_msg = f"\n💸 Wallet refunded: ${amt_f:.2f}"
    except Exception:
        # don't fail the flow if wallet refund fails
        pass

    await q.message.reply_text(
        "✅ Refund requested: cancelled + reported as 'no SMS'.\n"
        "Refund/credit depends on TextVerified eligibility."
        + refunded_msg
    )

    await _cleanup_otp_state(context.application, user_id)
   
   
   
   #RENTAL SHIT
   

# Function to send the service list with the buttons
async def send_service_list_with_buttons(update, context):
    try:
        # Log the start of sending the service list
        logger.info("Sending service list to user.")
        
        services = await get_services_for_export(capability="sms")
        logger.debug(f"Fetched services: {services}")

        
        # If no services found, log and return
        if not services:
            logger.error("No services found in the database.")
            await update.callback_query.message.reply_text("No available services found.")
            return


        # Assuming services are fetched from a function or DB
        service_list_text = (
            "If you've got the 4-digit Product ID, click ✅ Yes to continue.\n"
            "If you couldn't find the service you need, click ⏭ Universal to get a universal phone number.\n\n"
            "⚠️ Please make sure the service is not listed before using the universal phone number, "
            "or it may not receive OTP codes."
        )
        
        # Append the services dynamically to the message
        for service in services:
            service_list_text += f"Product ID: {service[0]} | Service: {service[1]}\n"
        
        # Create the buttons: Yes, I have the Product ID and Universal
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, I have the Product ID", callback_data="otp_rental_product_id"),
                InlineKeyboardButton("🌐 Universal", callback_data="otp_rental_universal")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Check if update.callback_query exists and use callback_query.message
        if update.callback_query:
            # Use callback_query.message to send the reply
            await update.callback_query.message.reply_text(service_list_text, reply_markup=reply_markup)
        else:
            # Handle case where update doesn't contain callback_query
            logger.error("Callback query is missing, cannot send service list.")
            return

        # Log successful message sending
        logger.info("Service list and buttons sent successfully.")

    except Exception as e:
        # Log any error that occurs
        logger.error(f"Error sending service list with buttons: {e}")
        if update.callback_query:
            # Send error message if callback_query exists
            await update.callback_query.message.reply_text("An error occurred while fetching the service list.")



