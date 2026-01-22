from textverified import TextVerified, NumberType, ReservationType, ReservationCapability
import os
import re
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



async def send_services_txt(update, context, capability: str = "sms"):
    data_bytes, filename = build_services_txt_bytes(capability=capability)

    bio = BytesIO(data_bytes)
    bio.name = filename  # telegram uses this as filename

    # Send the file (as a document) to the same chat
    await update.callback_query.message.reply_document(
        document=InputFile(bio, filename=filename),
        caption="✅ Here’s the service list.\nReply with the CODE you want.",
    )


# handlers/otp_handler.py

async def send_services_txt(update: Update, context: CallbackContext, *, capability: str = "sms") -> None:
    """
    Builds a txt file from DB in-memory and sends it to the user.
    """
    rows = get_services_for_export(capability=capability)

    # Build text content
    lines = []
    for code, name in rows:
        lines.append(f"Product ID: {code}\nService: {name}\n" + ("_" * 22) + "\n")

    content = "\n".join(lines) if lines else "No services found in DB."

    bio = BytesIO(content.encode("utf-8"))
    bio.name = f"services_{capability}.txt"
    bio.seek(0)

    chat_id = update.effective_chat.id
    await context.bot.send_document(
        chat_id=chat_id,
        document=InputFile(bio, filename=bio.name),
        caption="✅ TextVerified service list (from DB).",
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

    # ---- step: waiting for product id (4 digits) ----
    if step == "await_product_id":
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

        # no => go to final confirm w/ random state
        context.user_data["otp_state"] = None
        context.user_data["otp_step"] = "final_confirm"
        await _send_final_confirmation(update, context)
        return True

    # ---- step: waiting for state name ----
    if step == "await_state_name":
        ok, canon = normalize_us_state_full_name(text)
        if not ok:
            await update.message.reply_text("❌ Invalid state. Please enter full state name (e.g. California).")
            return True

        context.user_data["otp_state"] = canon
        context.user_data["otp_step"] = "final_confirm"
        await _send_final_confirmation(update, context)
        return True

    # ---- step: final confirm yes/no ----
    if step == "final_confirm":
        if low not in ("yes", "no"):
            await update.message.reply_text("Please reply with: yes or no")
            return True

        if low == "no":
            # cancel/reset and send them back (you can change where)
            context.user_data.pop("otp_step", None)
            context.user_data.pop("otp_service_name", None)
            context.user_data.pop("otp_state", None)
            await update.message.reply_text("✅ Cancelled.")
            return True

        # YES => reserve number hook
        service_name = context.user_data.get("otp_service_name") or "servicenotlisted"
        state = context.user_data.get("otp_state")

        # ✅ CALL YOUR RESERVE FUNCTION HERE
        # Example:
        # number = await reserve_number_for_otp(service_name=service_name, country="USA", state=state)
        # await update.message.reply_text(f"Reserved number for {service_name}: {number}\nWaiting for OTP...")

        await update.message.reply_text(
            f"✅ Confirmed.\n\nService: {service_name}\nState: {state or 'Random'}\n\n"
            "Now reserve the number (hook is ready in code)."
        )

        # clear flow
        context.user_data.pop("otp_step", None)
        context.user_data.pop("otp_service_name", None)
        context.user_data.pop("otp_state", None)
        return True

    return False




US_STATES_EXAMPLE = "California"

async def otp_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only handle normal user messages
    if not update.message or not update.message.text:
        return

    step = context.user_data.get("otp_step")
    if not step:
        return  # not in OTP flow, let other handlers process

    text = (update.message.text or "").strip().lower()

    # Step: expecting 4-digit Product ID
    if step == "awaiting_product_id":
        raw = (update.message.text or "").strip()
        if not re.fullmatch(r"\d{4}", raw):
            await update.message.reply_text("❌ Invalid. Please reply with exactly 4 digits (example: 0042).")
            return

        context.user_data["otp_product_id"] = raw
        context.user_data["otp_step"] = "universal_state_question"

        await update.message.reply_text(
            "If you've got the 4-digit Product ID, we’ll continue.\n\n"
            "Do you want the number to be generated from a specific US state?\n\n"
            "✅ Reply with: yes or no"
        )
        return

    # Step: yes/no for specific state
    if step == "universal_state_question":
        if text not in ("yes", "no"):
            await update.message.reply_text("❌ Please reply with: yes or no")
            return

        if text == "yes":
            context.user_data["otp_step"] = "awaiting_state_name"
            await update.message.reply_text(
                f"🇺🇸 Which US state do you want?\n\n✅ Example: {US_STATES_EXAMPLE}"
            )
            return

        # no -> random state
        context.user_data["otp_state"] = None
        context.user_data["otp_step"] = "final_confirmation"

        await update.message.reply_text(
            "✅ Random state selected.\n\n"
            "⚠️ Please reply with: yes or no to confirm."
        )
        return

    # Step: expecting a state name
    if step == "awaiting_state_name":
        state = (update.message.text or "").strip()
        if len(state) < 3:
            await update.message.reply_text("❌ Please type a valid US state name (example: California).")
            return

        context.user_data["otp_state"] = state
        context.user_data["otp_step"] = "final_confirmation"

        await update.message.reply_text(
            f"✅ State selected: {state}\n\n"
            "⚠️ Please reply with: yes or no to confirm."
        )
        return

    # Step: final confirmation
    if step == "final_confirmation":
        if text not in ("yes", "no"):
            await update.message.reply_text("❌ Please reply with: yes or no")
            return

        if text == "no":
            # reset just OTP flow bits
            context.user_data.pop("otp_step", None)
            context.user_data.pop("otp_product_id", None)
            context.user_data.pop("otp_state", None)
            await update.message.reply_text("❌ Cancelled.")
            return

        # yes -> proceed (you’ll plug your reserve-number logic here)
        product_id = context.user_data.get("otp_product_id")
        state = context.user_data.get("otp_state")

        await update.message.reply_text(
            f"✅ Confirmed.\n\nProduct ID: {product_id}\nState: {state or 'Random'}\n\nGenerating number..."
        )

        # TODO: call your reserve function next

        return



async def _send_final_confirmation(update: Update, context: CallbackContext) -> None:
    service_name = context.user_data.get("otp_service_name") or "servicenotlisted"
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
