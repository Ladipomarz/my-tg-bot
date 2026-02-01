from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton,ReplyKeyboardMarkup
from telegram.ext import ContextTypes
import asyncio
from telegram.ext import CallbackContext
from telegram import Update
from menus.tools_menu import (
    get_tools_inline,
    get_msn_services_menu,
    get_esim_duration_menu,
)
from menus.orders_menu import get_pending_order_menu
from utils.auto_delete import safe_send
from handlers.orders import ask_order_confirmation
from utils.db import get_pending_order
from handlers.otp_handler import reserve_number_for_otp
from handlers.otp_handler import(
    otp_verification_handler,
    otp_usa_one_time_or_rental_menu,
    otp_usa_rental_type_menu,
    otp_usa_monthly_duration_menu,
    show_usa_verification_menu,
)

from handlers.otp_handler import send_services_txt
from handlers.service_list_flow import start_service_list_flow
from handlers.otp_handler import otp_refund_now_cb
from handlers.payments import safe_edit_message
from handlers.rental import  send_service_list_with_buttons


from utils.validator import (
    is_valid_email,
    is_valid_name,
    is_valid_zip,
    normalize_us_state_full_name,
    suggest_us_states_full_name,
    is_valid_dob,
)


import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Example log for debugging
logger.debug("Bot started, awaiting commands...")



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
    print("Callback received for:", update.callback_query.data)
    q = update.callback_query
    data = q.data.strip()
    await q.answer()  # Acknowledge the button click

    # Early exit if there is no query data
    if not q or not q.data:
        return

    data = (q.data or "").strip()
    print(f"Received callback data: {data}")  # Debug log to ensure data is being captured
    user_id = update.effective_user.id

    # Any tools navigation cancels MSN text flow
    if data.startswith("tool_") and data != "tool_msn_lookup":
        _clear_msn_state(context)

    # Handle RDP service
    if data == "tool_rdp":
        _clear_msn_state(context)
        _clear_esim_state(context)
        await safe_send(
            q,
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
                q,
                context,
                f"🕒 You have a pending order {pending['order_code']}.\nWhat do you want to do?",
                reply_markup=get_pending_order_menu(),
            )
            return
        

    # Handling OTP menu
    # ---------- OTP ROUTER ----------

    if data == "tool_otp_usa":
        await otp_verification_handler(update, context, method="text")
        return
    
    # Handle the data if it's 'otp_usa'
    if data == "otp_usa":
        print("Handling otp_usa callback data in tools_callback...")  # Debug log
        await show_usa_verification_menu(update, context)  # Show the USA verification menu
        return
    
    if data == "tool_otp_usa_text":
    # Handle the OTP for Text Verification (you can add the logic to handle OTP fetching)
        await otp_usa_one_time_or_rental_menu(update, context, method="text") # Show one time and rental
    # (You can call the OTP provider's functions here to reserve a number and send OTP)
        return
    
    if data == "otp_usa_text_one_time":
        await start_service_list_flow(update, context, plan="one_time", capability="sms")
        return
    
    if data == "tool_otp_usa_voice":
        await update.callback_query.edit_message_text("Voice verification is coming soon! Stay tuned.")
        return

    if data == "otp_usa_text_rental":
        await otp_usa_rental_type_menu(update, context, "text")
        return

    if data == "otp_usa_voice_rental":
        await otp_usa_rental_type_menu(update, context, "voice")
        return
    if data == "otp_usa_text_rental_monthly":
        await otp_usa_monthly_duration_menu(update, context, "text")
        return

    if data == "otp_usa_voice_rental_monthly":
        await otp_usa_monthly_duration_menu(update, context, "voice")
        return
    
    if data == "otp_have_id":
    # Next step: ask user to reply with the 4-digit Product ID
        context.user_data["otp_step"] = "awaiting_product_id"
        await update.callback_query.edit_message_text(
        "✅ Great. Please reply with the 4-digit Product ID (example: 0042)."
    )
        return

    if data == "otp_skip_universal":
        context.user_data.pop("otp_service_name", None)
        context.user_data["otp_custom_service"] = "General Service"
        context.user_data["otp_api_service_name"] = "servicenotlisted"
        context.user_data["otp_step"] = "ask_specific_state"

        await update.callback_query.edit_message_text(
            "Do you want the number to be generated from a specific US state?\n\n"
            "✅ Reply with: yes or no"
        )
        return


    if data == "otp_refund_now":
        await otp_refund_now_cb(update, context)
        return
    
    
    if data == "otp_rental_product_id":
        
        logger.debug(f"Received callback data: {data}")
         # Next step: ask user to reply with the 4-digit Product ID
        context.user_data["otp_step"] = "awaiting_product_id"
        await update.callback_query.edit_message_text(
        "✅ Great. Please reply with the 4-digit Product ID (example: 0042)."
    )
    
     
        # Fix: Correctly extract rental duration from the callback data
    if data.startswith("otp_usa_text_rental_monthly_"):
        # Extract the number part before 'm' (1m, 2m, or 3m)
        rental_months = int(data.split('_')[-1][0])  # Split the data and get the first digit (before 'm')
        logger.debug(f"Rental duration selected: {rental_months} months")

        context.user_data['rental_months'] = rental_months

        # Send the services list and proceed to the next flow
        await send_service_list_with_buttons(update, context)
        return
    
    
    
        
    if data == "social_menu":
        await safe_edit_message(q, context, "📣 Social Services\n\n🚧 Coming soon.")
        await asyncio.sleep(1.5)
        await safe_edit_message(q, context, "🧰 Tools:", reply_markup=get_tools_inline())
        return


    
# BACK NAVIGATION
    if data == "otp_back_tools":
        await safe_send(q, context, "Tools:", reply_markup=get_tools_inline())
        return
    if data == "otp_back_country":
        await show_usa_verification_menu(update, context)
        return

    if data == "otp_back_verification":
        await show_usa_verification_menu(update, context)
        return
    if data == "otp_back_usa_one_time_rental":
    # default back to text for now
        await otp_usa_one_time_or_rental_menu(update, context, "text")
        return

    if data == "otp_back_usa_rental_type":
        await otp_usa_rental_type_menu(update, context, "text")
        return
    
    
    if data.startswith("service_"):
        service_name = data.replace("service_", "")  # Extract the service name
        number = await reserve_number_for_otp(service_name=service_name, country="USA")  # Correct invocation
        await update.callback_query.edit_message_text(
            f"Reserved number for {service_name}: {number}\nWaiting for OTP..."
        )
        return
    
    
    # If unhandled data, log it
    print(f"Unhandled callback data: {data}")
    
    

    # Handling other tools (MSN, eSIM, etc.)
    if data == "tool_msn_services":
        _clear_msn_state(context)
        await safe_send(
            q, context, "MSN Services:", reply_markup=get_msn_services_menu()
        )
        return

    if data == "tool_back_tools":
        _clear_msn_state(context)
        _clear_esim_state(context)
        await safe_send(q, context, "Tools:", reply_markup=get_tools_inline())
        return

    if data == "tool_msn_lookup":
        _clear_msn_state(context)
        context.user_data["msn_step"] = "first_name"
        await safe_send(
            q, context, _prompt_for_step("first_name"), reply_markup=msn_nav_kb()
        )
        return

    if data == "tool_msn_magic":
        _clear_msn_state(context)
        await safe_send(
            q,
            context,
            "MSN Magic Coming Soon...",
            reply_markup=get_msn_services_menu(),
        )
        return
    
async def open_tools_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Opens the Tools menu from the ReplyKeyboard 'Tools' button.
    This is used by handlers/start.py.
    """
    await update.message.reply_text("Tools:", reply_markup=get_tools_inline())
    

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
