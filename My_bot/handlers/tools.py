from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.ext import CallbackContext
from telegram import Update
from telegram.error import BadRequest

from menus.tools_menu import (
    get_tools_inline,
    get_msn_services_menu,
    get_esim_duration_menu,
)
from menus.orders_menu import get_pending_order_menu
from utils.auto_delete import safe_send
from handlers.orders import ask_order_confirmation
from utils.db import get_pending_order
from config import API_KEY 
from handlers.otp_handler import reserve_number_for_otp




from utils.validator import (
    is_valid_email,
    is_valid_name,
    is_valid_zip,
    normalize_us_state_full_name,
    suggest_us_states_full_name,
    is_valid_dob,
)


# ---------- UI HELPERS ----------


def msn_nav_kb() -> InlineKeyboardMarkup:
    # Back + Cancel (2 buttons)
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⬅ Back", callback_data="msn_back"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_msn"),
            ]
        ]
    )


def _clear_msn_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in [
        "msn_step",
        "first_name",
        "last_name",
        "type",
        "dob",
        "info",
        "from_msn",
    ]:
        context.user_data.pop(key, None)


def _clear_esim_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    # include esim_step so email prompt state clears too
    for key in [
        "esim_step",
        "esim_duration",
        "esim_country",
        "custom_price_usd",
        "esim_email",
    ]:
        context.user_data.pop(key, None)


def _msn_prev_step(curr: str) -> str | None:
    order = ["first_name", "last_name", "type", "dob", "info"]
    if curr not in order:
        return None
    i = order.index(curr)
    return order[i - 1] if i > 0 else None


def _prompt_for_step(step: str, lookup_type: str | None = None) -> str:
    if step == "first_name":
        return "Enter First Name:"
    if step == "last_name":
        return "Enter Last Name:"
    if step == "type":
        return "Select Type:\n" "1️⃣ City\n" "2️⃣ DOB\n" "3️⃣ State\n" "4️⃣ ZIP Code"
    if step == "dob":
        return "Enter DOB (YYYY/MM/DD or YYYY-MM-DD):"
    if step == "info":
        if lookup_type == "1":
            return "Enter City:"
        if lookup_type == "3":
            return "Enter State (full name only, e.g. Texas):"
        if lookup_type == "4":
            return "Enter ZIP Code (5 digits or ZIP+4):"
        return "Enter information:"
    return "Enter information:"


def _normalize_dob_input(dob_str: str) -> str:
    # Accept YYYY-MM-DD and convert to YYYY/MM/DD for validator
    s = (dob_str or "").strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s.replace("-", "/")
    return s


# ---------- TOOLS MENU + CALLBACKS ----------

async def tools_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()  # Acknowledge the button click

    # Early exit if there is no query data
    if not query or not query.data:
        return

    data = (query.data or "").strip()
    user_id = update.effective_user.id

    # Any tools navigation cancels MSN text flow
    if data.startswith("tool_") and data != "tool_msn_lookup":
        _clear_msn_state(context)

    # Handle RDP service
    if data == "tool_rdp":
        _clear_msn_state(context)
        _clear_esim_state(context)
        await safe_send(
            query,
            context,
            "🖥️ RDP Service\n\nComing soon…",
            reply_markup=get_tools_inline(),
        )
        return

    # Pending-order gate (block if unpaid)
    pending = get_pending_order(user_id)
    if pending and pending.get("status") == "pending":
        pay_status = (pending.get("pay_status") or "").lower().strip()
        if pay_status in {"pending", "", "new"}:
            await safe_send(
                query,
                context,
                f"🕒 You have a pending order {pending['order_code']}.\nWhat do you want to do?",
                reply_markup=get_pending_order_menu(),
            )
            return

    # Handling OTP menu
    if data == "tool_otp":
        # Show OTP verification menu
        await show_otp_menu(update, context)

    if data == "tool_otp_usa":
        # Reserve number using TextVerified
        number = await reserve_number_for_otp(country="USA")  # Reserve the number via TextVerified
        await update.callback_query.edit_message_text(
            f"Reserved number: {number}\nWaiting for OTP..."
        )


    # Handling other tools (MSN, eSIM, etc.)
    if data == "tool_msn_services":
        _clear_msn_state(context)
        await safe_send(
            query, context, "MSN Services:", reply_markup=get_msn_services_menu()
        )
        return

    if data == "tool_back_tools":
        _clear_msn_state(context)
        _clear_esim_state(context)
        await safe_send(query, context, "Tools:", reply_markup=get_tools_inline())
        return

    if data == "tool_msn_lookup":
        _clear_msn_state(context)
        context.user_data["msn_step"] = "first_name"
        await safe_send(
            query, context, _prompt_for_step("first_name"), reply_markup=msn_nav_kb()
        )
        return

    if data == "tool_msn_magic":
        _clear_msn_state(context)
        await safe_send(
            query,
            context,
            "MSN Magic Coming Soon...",
            reply_markup=get_msn_services_menu(),
        )
        return

    

async def show_otp_menu(update: Update, context: CallbackContext):
    # Define the keyboard with 2 buttons in the first row and 1 button in the second row
    keyboard = [
        [InlineKeyboardButton("USA Number 🇺🇸", callback_data="tool_otp_usa"),
         InlineKeyboardButton("Other Countries 🌍", callback_data="tool_otp_other")],
        [InlineKeyboardButton("⬅ Back", callback_data="tool_back_tools")]
    ]
    
    # Create the reply markup for the inline keyboard
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Send the OTP menu with the keyboard
    await update.callback_query.edit_message_text(
        "Please choose the verification type:",
        reply_markup=reply_markup
    )

    try:
        await update.callback_query.edit_message_text(
            "Please choose the verification type:",
            reply_markup=reply_markup
        )
    except BadRequest as e:
        # Ignore only the "Message is not modified" error
        if "Message is not modified" in str(e):
            return
        raise

        

   

async def open_tools_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Opens the Tools menu from the ReplyKeyboard 'Tools' button.
    This is used by handlers/start.py.
    """
    await update.message.reply_text("Tools:", reply_markup=get_tools_inline())
    

async def show_usa_verification_menu(update, context):
    keyboard = [
        [
            InlineKeyboardButton("Text Verification", callback_data="tool_otp_usa_text"),
            InlineKeyboardButton("Voice Verification (Soon)", callback_data="tool_otp_usa_voice"),
        ],
        [InlineKeyboardButton("⬅ Back", callback_data="tool_otp")],
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
        raise

    


# ---------- MSN USER INPUT FLOW ----------


async def handle_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("msn_step")
    if not step:
        return

    text = (update.message.text or "").strip()
    context.user_data["from_msn"] = True

    # STEP 1: First Name
    if step == "first_name":
        if not is_valid_name(text):
            await safe_send(
                update,
                context,
                "❌ Invalid first name.\nUse letters only (spaces / - / ' allowed).",
                reply_markup=msn_nav_kb(),
            )
            return

        context.user_data["first_name"] = text
        context.user_data["msn_step"] = "last_name"
        await safe_send(
            update, context, _prompt_for_step("last_name"), reply_markup=msn_nav_kb()
        )
        return

    # STEP 2: Last Name
    if step == "last_name":
        if not is_valid_name(text):
            await safe_send(
                update,
                context,
                "❌ Invalid last name.\nUse letters only (spaces / - / ' allowed).",
                reply_markup=msn_nav_kb(),
            )
            return

        context.user_data["last_name"] = text
        context.user_data["msn_step"] = "type"
        await safe_send(
            update, context, _prompt_for_step("type"), reply_markup=msn_nav_kb()
        )
        return

    # STEP 3: Select Lookup Type
    if step == "type":
        if text not in {"1", "2", "3", "4"}:
            await safe_send(
                update,
                context,
                "❌ Invalid option.\n\n"
                "Reply with:\n"
                "1️⃣ City\n"
                "2️⃣ DOB\n"
                "3️⃣ State\n"
                "4️⃣ ZIP Code",
                reply_markup=msn_nav_kb(),
            )
            return

        context.user_data["type"] = text

        if text == "2":
            context.user_data["msn_step"] = "dob"
            await safe_send(
                update, context, _prompt_for_step("dob"), reply_markup=msn_nav_kb()
            )
            return

        context.user_data["msn_step"] = "info"
        await safe_send(
            update, context, _prompt_for_step("info", text), reply_markup=msn_nav_kb()
        )
        return

    # STEP 4: DOB
    if step == "dob":
        dob_norm = _normalize_dob_input(text)
        if not is_valid_dob(dob_norm):
            await safe_send(
                update,
                context,
                "❌ Invalid DOB.\nUse YYYY/MM/DD or YYYY-MM-DD (e.g. 1995-08-21).",
                reply_markup=msn_nav_kb(),
            )
            return

        context.user_data["dob"] = dob_norm
        context.user_data.pop("msn_step", None)

        await ask_order_confirmation(
            update, context, "Order Almost Done!. 🔍", "MSN Services"
        )
        return

    # STEP 5: Info
    if step == "info":
        chosen_type = context.user_data.get("type")

        if chosen_type == "1":  # City
            if not is_valid_name(text):
                await safe_send(
                    update,
                    context,
                    "❌ Invalid city.\nUse letters only.",
                    reply_markup=msn_nav_kb(),
                )
                return
            context.user_data["info"] = text

        elif chosen_type == "3":  # State (full name only)
            ok, canon = normalize_us_state_full_name(text)
            if not ok:
                suggestions = suggest_us_states_full_name(text)
                extra = "\n".join(f"• {s}" for s in suggestions) if suggestions else ""
                msg = "❌ Invalid state.\nEnter full state name only (e.g. Texas, California, New York)."
                if extra:
                    msg += "\n\nDid you mean:\n" + extra
                await safe_send(update, context, msg, reply_markup=msn_nav_kb())
                return
            context.user_data["info"] = canon

        elif chosen_type == "4":  # ZIP
            if not is_valid_zip(text):
                await safe_send(
                    update,
                    context,
                    "❌ Invalid ZIP code.\nUse 5 digits (e.g. 90210) or ZIP+4 (e.g. 90210-1234).",
                    reply_markup=msn_nav_kb(),
                )
                return
            context.user_data["info"] = text

        else:
            context.user_data["info"] = text

        context.user_data.pop("msn_step", None)
        await ask_order_confirmation(
            update, context, "Order Almost Done!. 🔍", "MSN Services"
        )
        return


# ---------- eSIM USER INPUT FLOW ----------


async def handle_esim_email_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("esim_step") != "email":
        return

    email = (update.message.text or "").strip()
    if not is_valid_email(email):
        await safe_send(
            update, context, "❌ Invalid email. Try again (example: name@gmail.com)."
        )
        return

    context.user_data["esim_email"] = email
    context.user_data.pop("esim_step", None)

    duration = context.user_data.get("esim_duration", "")
    amount_usd = context.user_data.get("custom_price_usd", "")
    pretty = {"1m": "1 Month", "3m": "3 Months", "1y": "1 Year"}.get(duration, duration)

    # ✅ store email in DB via description
    order_description = f"eSIM USA - {pretty} | Email: {email}"

    display_text = (
        "Order Almost Done!. 🛜\n\n"
        f"✅ {order_description}\n"
        f"💵 Price: ${amount_usd}"
    )

    await ask_order_confirmation(update, context, display_text, order_description)


from .provider_factory import get_otp_provider
from config import API_KEY  # Your real TextVerified API key
