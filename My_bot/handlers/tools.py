from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from menus.tools_menu import get_tools_inline, get_ssn_services_menu
from menus.orders_menu import get_pending_order_menu
from utils.validator import is_valid_dob, is_valid_name
from utils.auto_delete import safe_send
from handlers.orders import ask_order_confirmation
from utils.db import get_pending_order


# ---------- UI HELPERS ----------

def get_cancel_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_ssn")]]
    )


def _clear_ssn_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear only SSN-related keys."""
    for key in ["ssn_step", "first_name", "last_name", "type", "dob", "info", "from_ssn"]:
        context.user_data.pop(key, None)


# ---------- TOOLS MENU + SSN CALLBACKS ----------

async def open_tools_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_send(
        update,
        context,
        "Tools:",
        reply_markup=get_tools_inline(),
    )


async def tools_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ✅ This handler is for INLINE BUTTON callbacks
    query = update.callback_query
    if not query or not query.data:
        return

    data = (query.data or "").strip()
    user_id = update.effective_user.id

    # ✅ Pending-order gate:
    # block ONLY if payment is NOT detected yet
    pending = get_pending_order(user_id)
    if pending and pending.get("status") == "pending":
        pay_status = (pending.get("pay_status") or "").lower().strip()

        # unpaid / invoice-created only
        if pay_status in {"pending", "", "new"}:
            await safe_send(
                query,
                context,
                f"🕒 You have a pending order {pending['order_code']}.\nWhat do you want to do?",
                reply_markup=get_pending_order_menu(),
            )
            return
        # ✅ detected/paid -> allow normal tools

    # --- NOW handle actual tool buttons ---

    # SSN Services menu  ✅ (this is what your "Services" button sends)
    if data == "tool_ssn_services":
        await safe_send(
            query,
            context,
            "SSN Services:",
            reply_markup=get_ssn_services_menu(),
        )
        return

    # Back to Tools Menu
    if data == "tool_back_tools":
        _clear_ssn_state(context)
        await safe_send(
            query,
            context,
            "Tools:",
            reply_markup=get_tools_inline(),
        )
        return

    # Cancel SSN flow
    if data == "cancel_ssn":
        _clear_ssn_state(context)
        await safe_send(query, context, "SSN flow cancelled.")
        return

    # Start SSN lookup flow
    if data == "tool_ssn_lookup":
        _clear_ssn_state(context)
        context.user_data["ssn_step"] = "first_name"

        await safe_send(
            query,
            context,
            "Enter First Name:",
            reply_markup=get_cancel_button(),
        )
        return

    # SSN Magic placeholder
    if data == "tool_ssn_magic":
        await safe_send(
            query,
            context,
            "SSN Magic Coming Soon...",
            reply_markup=get_ssn_services_menu(),
        )
        return


# ---------- SSN USER INPUT FLOW ----------

async def handle_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles text input when in SSN flow.
    """
    step = context.user_data.get("ssn_step")
    if not step:
        return

    text = (update.message.text or "").strip()
    context.user_data["from_ssn"] = True

    # STEP 1: First Name
    if step == "first_name":
        if not is_valid_name(text):
            await safe_send(
                update,
                context,
                "❌ Invalid first name.\nUse letters only.",
                reply_markup=get_cancel_button(),
            )
            return

        context.user_data["first_name"] = text
        context.user_data["ssn_step"] = "last_name"
        await safe_send(update, context, "Enter Last Name:", reply_markup=get_cancel_button())
        return

    # STEP 2: Last Name
    if step == "last_name":
        if not is_valid_name(text):
            await safe_send(
                update,
                context,
                "❌ Invalid last name.\nUse letters only.",
                reply_markup=get_cancel_button(),
            )
            return

        context.user_data["last_name"] = text
        context.user_data["ssn_step"] = "type"
        await safe_send(
            update,
            context,
            "Select Type:\n1️⃣ City\n2️⃣ DOB\n3️⃣ State\n4️⃣ ZIP",
            reply_markup=get_cancel_button(),
        )
        return

    # STEP 3: Select Lookup Type
    if step == "type":
        if text not in ["1", "2", "3", "4"]:
            await safe_send(update, context, "Enter 1, 2, 3 or 4:", reply_markup=get_cancel_button())
            return

        context.user_data["type"] = text

        if text == "2":
            context.user_data["ssn_step"] = "dob"
            await safe_send(update, context, "Enter DOB (YYYY/MM/DD):", reply_markup=get_cancel_button())
        else:
            context.user_data["ssn_step"] = "info"
            await safe_send(update, context, "Enter information:", reply_markup=get_cancel_button())
        return

    # STEP 4: DOB
    if step == "dob":
        if not is_valid_dob(text):
            await safe_send(
                update,
                context,
                "❌ Invalid DOB format.\nUse: YYYY/MM/DD (e.g. 1995/08/21)",
                reply_markup=get_cancel_button(),
            )
            return

        context.user_data["dob"] = text
        context.user_data.pop("ssn_step", None)

        display_text = "Order Almost Done!. 🔍"
        order_description = "SSN Services"
        await ask_order_confirmation(update, context, display_text, order_description)
        return

    # STEP 5: Info
    if step == "info":
        if not text:
            await safe_send(update, context, "Enter information:", reply_markup=get_cancel_button())
            return

        context.user_data["info"] = text
        context.user_data.pop("ssn_step", None)

        display_text = "Order Almost Done!. 🔍"
        order_description = "SSN Services"
        await ask_order_confirmation(update, context, display_text, order_description)
        return
