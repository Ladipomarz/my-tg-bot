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
from utils.validator import normalize_us_state_full_name
import datetime
from typing import Optional
from telegram.constants import ParseMode


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


async def _cleanup_otp_state(app, user_id: int) -> None:
    ud = app.user_data.get(user_id)
    if not ud:
        return
    for k in (
        "otp_step",
        "otp_service_name",
        "otp_state",
        "otp_verification_id",
        "otp_reserved_number",
        "otp_reserved_at_utc",
        "otp_poll_job_name",
        "otp_refund_job_name",
    ):
        ud.pop(k, None)


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

        # Prices placeholder (you said you'll set later)
        specific_price = context.user_data.get("otp_specific_price", "$x")
        random_price = context.user_data.get("otp_random_price", "$y")
        
        if low == "yes":
            context.user_data["otp_step"] = "await_state_name"
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
        print(f"[STATE] Step: {step}")
        print(f"[STATE] User input for state: {state_name!r}")
        print(f"[STATE] User data before state check: {dict(context.user_data)}")
        
        
        if not state_name:
            await update.message.reply_text("❌ Please enter a valid state name (e.g. California).")
            return True

        ok, canon = normalize_us_state_full_name(state_name)
        
        if ok:
            print(f"Valid state: {canon}")  # Log if state is valid
            context.user_data["otp_state"] = canon
            context.user_data["otp_step"] = "final_confirm"
            await _send_final_confirmation(update, context)
            return True
        else:
            print(f"Invalid state: {state_name}")  # Log invalid state
            await update.message.reply_text("❌ Invalid state. Please enter the full state name (e.g. California).")
            return True



    # ---- step: final confirm yes/no ----
    if step == "final_confirm":
        low = update.message.text.lower()  # To handle user input correctly
        
        if low not in ("yes", "no"):
            await update.message.reply_text("Please reply with: yes or no")
            return True

        if low == "no":
            # If "No" is selected, cancel the process and clear data
            context.user_data.pop("otp_step", None)
            context.user_data.pop("otp_service_name", None)
            context.user_data.pop("otp_state", None)
            context.user_data.pop("otp_custom_service", None)

            # Inform the user that the process has been cancelled
            await update.message.reply_text("✅ The process has been cancelled.")
            return True
        
        if low == "yes":
            # Proceed with OTP generation (or any further steps)
            selected = context.user_data.get("otp_service_name")
            service_name = selected if selected else "General Service"
            state = context.user_data.get("otp_state", "Random")

            # Proceed to reserve number and generate OTP
            try:
                ver = await reserve_sms_verification(
                    service_name=service_name,
                    state=state,
                )

                number = (
                    getattr(ver, "number", None)
                    or getattr(ver, "phone_number", None)
                    or getattr(ver, "to_value", None)
                )
                verification_id = (
                    getattr(ver, "id", None)
                    or getattr(ver, "verification_id", None)
                    or getattr(ver, "reservation_id", None)
                )
                print(f"Reserved number: {number}, Verification ID: {verification_id}")  # Log number and verification ID


                context.user_data["otp_verification_id"] = verification_id
                context.user_data["otp_reserved_number"] = number
                context.user_data["otp_reserved_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

                intl_num = format_us_international(number)
                local_num = format_us_local(number)

                await update.message.reply_text(
                    (
                        "<b>✅ Reserved number!</b>\n\n"
                        f"<b>Service:</b> {service_name}\n"
                        f"<b>State:</b> {state or 'Random'}\n"
                        f"<b>Number (Intl):</b> {intl_num}\n"
                        f"<b>Number (Local):</b> {local_num}\n"
                        f"<b>Verification ID:</b> {verification_id}\n\n"
                        "⏳ Waiting for OTP… I’ll auto-check every 5 seconds (up to 5 minutes)."
                    ),
                    parse_mode=ParseMode.HTML,
                    reply_markup=refund_kb(),
                )

                await start_otp_auto_poll(update, context, verification_id)

            except Exception as e:
                await update.message.reply_text(f"❌ Failed to reserve number: {e}")
                return True

            # Clear flow step (keep reservation info so you can poll OTP)
            context.user_data.pop("otp_step", None)
            context.user_data.pop("otp_service_name", None)
            context.user_data.pop("otp_state", None)
            return True


US_STATES_EXAMPLE = "California"

async def _send_final_confirmation(update: Update, context: CallbackContext) -> None:
    service_name = context.user_data.get("otp_service_name") or "General Service"
    state = context.user_data.get("otp_state")

    price = context.user_data.get("otp_price", "$x")  # placeholder
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

async def reserve_sms_verification(service_name: str, state: str | None, service_not_listed_name: str | None = None):
    kwargs = {"service_name": service_name, "state": state}
    if service_not_listed_name:
        kwargs["service_not_listed_name"] = service_not_listed_name
        return await asyncio.to_thread(lambda: provider.verifications.create(**kwargs))

    """
    Creates an SMS verification and returns the verification object.
    Runs in a thread because the SDK calls are sync.
    """
    def _do():
        kwargs = {
            "service_name": service_name,
            "capability": ReservationCapability.SMS,
        }

        if state:
            acs = _area_codes_for_state(state)
            if acs:
                # pass a short list to avoid massive payloads
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
    chat_id = data["chat_id"]
    user_id = data["user_id"]
    verification_id = data["verification_id"]
    reserved_at_iso = data["reserved_at_utc"]

    # Parse reservation timestamp
    since_dt = datetime.datetime.fromisoformat(reserved_at_iso)
    if since_dt.tzinfo is None:
        since_dt = since_dt.replace(tzinfo=datetime.timezone.utc)

    try:
        result = await asyncio.to_thread(_poll_textverified_once, verification_id, since_dt)
    except Exception as e:
        # don’t spam; just stop on hard errors
        await context.bot.send_message(chat_id=chat_id, text=f"❌ OTP polling error: {e}")
        # stop jobs
        poll_name = data.get("poll_job_name")
        refund_name = data.get("refund_job_name")
        if poll_name:
            _remove_jobs_by_name(context.job_queue, poll_name)
        if refund_name:
            _remove_jobs_by_name(context.job_queue, refund_name)
        await _cleanup_otp_state(context.application, user_id)
        return

    if not result:
        return  # no OTP yet, next tick will try again

    code = result.get("code") or "N/A"
    content = (result.get("content") or "").strip()
    from_ = result.get("from") or "Unknown"

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "✅ OTP received!\n\n"
            f"Code: {code}\n"
            f"From: {from_}\n"
            f"Message: {content}"
        ),
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
    # best effort: cancel first
    if hasattr(provider, "verifications") and hasattr(provider.verifications, "cancel"):
        provider.verifications.cancel(verification_id)

    # best effort: report issue for “no SMS” if supported by SDK
    if hasattr(provider, "verifications") and hasattr(provider.verifications, "report"):
        try:
            provider.verifications.report(verification_id)
        except Exception:
            pass


async def _otp_refund_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data or {}
    chat_id = data["chat_id"]
    user_id = data["user_id"]
    verification_id = data["verification_id"]
    poll_name = data.get("poll_job_name")

    # If polling job no longer exists, OTP was received/cancelled already
    if poll_name and context.job_queue.get_jobs_by_name(poll_name) == []:
        return

    # stop polling
    if poll_name:
        _remove_jobs_by_name(context.job_queue, poll_name)

    # refund attempt
    try:
        await asyncio.to_thread(_cancel_and_report_blocking, verification_id)
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Refund attempt failed: {e}")
        await _cleanup_otp_state(context.application, user_id)
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "⌛ No OTP received within 5 minutes.\n"
            "I cancelled the verification and reported it as 'no SMS' (refund/credit depends on TextVerified eligibility)."
        ),
    )

    await _cleanup_otp_state(context.application, user_id)
    
    
async def start_otp_auto_poll(update: Update, context: ContextTypes.DEFAULT_TYPE, verification_id: str) -> None:
    """
    Starts repeating poll (every 5s) + a 5-minute refund watchdog.
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
        "verification_id": verification_id,
        "reserved_at_utc": reserved_at_iso,
        "poll_job_name": poll_name,
        "refund_job_name": refund_name,
    }

    context.user_data["otp_poll_job_name"] = poll_name
    context.user_data["otp_refund_job_name"] = refund_name

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
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id
    chat_id = q.message.chat_id

    # read state
    ud = context.application.user_data.get(user_id, {})
    verification_id = ud.get("otp_verification_id") or context.user_data.get("otp_verification_id")
    poll_name = ud.get("otp_poll_job_name") or context.user_data.get("otp_poll_job_name")
    refund_name = ud.get("otp_refund_job_name") or context.user_data.get("otp_refund_job_name")

    if not verification_id:
        await q.message.reply_text("❌ No active verification to refund.")
        return

    # stop jobs
    if poll_name:
        _remove_jobs_by_name(context.job_queue, poll_name)
    if refund_name:
        _remove_jobs_by_name(context.job_queue, refund_name)

    # reuse same refund action
    try:
        await asyncio.to_thread(_cancel_and_report_blocking, verification_id)
    except Exception as e:
        await q.message.reply_text(f"❌ Refund attempt failed: {e}")
        await _cleanup_otp_state(context.application, user_id)
        return

    await q.message.reply_text(
        "✅ Refund requested: cancelled + reported as 'no SMS'.\n"
        "Refund/credit depends on TextVerified eligibility."
    )

    await _cleanup_otp_state(context.application, user_id)
    