from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from menus.tools_menu import get_tools_inline, get_ssn_services_menu, get_esim_duration_menu
from menus.orders_menu import get_pending_order_menu
from utils.auto_delete import safe_send
from handlers.orders import ask_order_confirmation
from utils.db import get_pending_order

from utils.validator import (
    is_valid_name,
    is_valid_zip,
    normalize_us_state_full_name,
    suggest_us_states_full_name,
    is_valid_dob,  # we will support YYYY-MM-DD by normalizing before calling
)


# ---------- UI HELPERS ----------

def ssn_nav_kb() -> InlineKeyboardMarkup:
    # Back + Cancel (2 buttons)
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅ Back", callback_data="ssn_back"),
        InlineKeyboardButton("❌ Cancel", callback_data="cancel_ssn"),
    ]])


def _clear_ssn_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in ["ssn_step", "first_name", "last_name", "type", "dob", "info", "from_ssn"]:
        context.user_data.pop(key, None)


def _clear_esim_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in ["esim_duration", "esim_country", "custom_price_usd"]:
        context.user_data.pop(key, None)


def _ssn_prev_step(curr: str) -> str | None:
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
        return (
            "Select Type:\n"
            "1️⃣ City\n"
            "2️⃣ DOB\n"
            "3️⃣ State\n"
            "4️⃣ ZIP Code"
        )
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

async def open_tools_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_send(update, context, "Tools:", reply_markup=get_tools_inline())


async def tools_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return

    data = (query.data or "").strip()
    user_id = update.effective_user.id

    # Any tools navigation cancels SSN text flow (prevents "Invalid first name" when navigating)
    if data.startswith("tool_") and data != "tool_ssn_lookup":
        _clear_ssn_state(context)

    # ... rest of your logic ...



    # Pending-order gate (block only if unpaid)
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

    # ---------- SSN NAV BUTTONS ----------
    if data == "ssn_back":
        step = context.user_data.get("ssn_step")
        if not step:
            # if no step, go back to SSN services menu
            await safe_send(query, context, "SSN Services:", reply_markup=get_ssn_services_menu())
            return

        prev = _ssn_prev_step(step)
        if not prev:
            # at first step -> back to SSN services menu
            _clear_ssn_state(context)
            await safe_send(query, context, "SSN Services:", reply_markup=get_ssn_services_menu())
            return

        # Move back
        context.user_data["ssn_step"] = prev
        lookup_type = context.user_data.get("type")
        await safe_send(query, context, _prompt_for_step(prev, lookup_type), reply_markup=ssn_nav_kb())
        return

    if data == "cancel_ssn":
        _clear_ssn_state(context)
        await safe_send(query, context, "SSN flow cancelled.")
        return

    # ---------- eSIM ----------
    if data == "esim_services":
        _clear_esim_state(context)
        context.user_data["esim_country"] = "USA"

        await safe_send(
            query,
            context,
            "🛜 eSIM Service\nCountry: 🇺🇸 USA (default)\n🔁 Renewable\n\nSelect duration:",
            reply_markup=get_esim_duration_menu(),
        )
        return

    if data.startswith("esim_duration:"):
        duration = data.split(":", 1)[1].strip()  # 1m / 3m / 1y
        context.user_data["esim_duration"] = duration
        context.user_data["esim_country"] = "USA"

        from pricelist import ESIM_PRICES_USD
        if duration not in ESIM_PRICES_USD:
            await safe_send(query, context, "❌ Invalid duration.", reply_markup=get_esim_duration_menu())
            return

        amount_usd = ESIM_PRICES_USD[duration]
        context.user_data["custom_price_usd"] = amount_usd

        pretty = {"1m": "1 Month", "3m": "3 Months", "1y": "1 Year"}.get(duration, duration)
        order_description = f"eSIM USA - {pretty}"
        display_text = (
            "Order Almost Done!. 🛜\n\n"
            f"✅ {order_description}\n"
            f"💵 Price: ${amount_usd}"
        )
        await ask_order_confirmation(query, context, display_text, order_description)
        return

    # ---------- Tools menus ----------
    # SSN Services menu ✅
    if data == "tool_ssn_services":
        _clear_ssn_state(context)  # ✅ exit any SSN input mode
        await safe_send(query, context, "SSN Services:", reply_markup=get_ssn_services_menu())
        return

    # Back to Tools Menu
    if data == "tool_back_tools":
        _clear_ssn_state(context)
        _clear_esim_state(context)
        await safe_send(
            query,
            context,
            "Tools:",
            reply_markup=get_tools_inline(),
        )
        return

    # Start SSN lookup flow
    if data == "tool_ssn_lookup":
        _clear_ssn_state(context)
        context.user_data["ssn_step"] = "first_name"
        await safe_send(query, context, _prompt_for_step("first_name"), reply_markup=ssn_nav_kb())
        return

    # SSN Magic placeholder
    if data == "tool_ssn_magic":
        _clear_ssn_state(context)  # ✅ exit any SSN input mode
        await safe_send(query, context, "SSN Magic Coming Soon...", reply_markup=get_ssn_services_menu())
        return



# ---------- SSN USER INPUT FLOW ----------

async def handle_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("ssn_step")
    if not step:
        return

    text = (update.message.text or "").strip()
    context.user_data["from_ssn"] = True

    # STEP 1: First Name
    if step == "first_name":
        if not is_valid_name(text):
            await safe_send(update, context, "❌ Invalid first name.\nUse letters only (spaces / - / ' allowed).", reply_markup=ssn_nav_kb())
            return

        context.user_data["first_name"] = text
        context.user_data["ssn_step"] = "last_name"
        await safe_send(update, context, _prompt_for_step("last_name"), reply_markup=ssn_nav_kb())
        return

    # STEP 2: Last Name
    if step == "last_name":
        if not is_valid_name(text):
            await safe_send(update, context, "❌ Invalid last name.\nUse letters only (spaces / - / ' allowed).", reply_markup=ssn_nav_kb())
            return

        context.user_data["last_name"] = text
        context.user_data["ssn_step"] = "type"
        await safe_send(update, context, _prompt_for_step("type"), reply_markup=ssn_nav_kb())
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
                reply_markup=ssn_nav_kb(),
            )
            return

        context.user_data["type"] = text

        if text == "2":
            context.user_data["ssn_step"] = "dob"
            await safe_send(update, context, _prompt_for_step("dob"), reply_markup=ssn_nav_kb())
            return

        context.user_data["ssn_step"] = "info"
        await safe_send(update, context, _prompt_for_step("info", text), reply_markup=ssn_nav_kb())
        return

    # STEP 4: DOB
    if step == "dob":
        dob_norm = _normalize_dob_input(text)
        if not is_valid_dob(dob_norm):
            await safe_send(
                update,
                context,
                "❌ Invalid DOB.\nUse YYYY/MM/DD or YYYY-MM-DD (e.g. 1995-08-21).",
                reply_markup=ssn_nav_kb(),
            )
            return

        context.user_data["dob"] = dob_norm  # store normalized
        context.user_data.pop("ssn_step", None)

        display_text = "Order Almost Done!. 🔍"
        order_description = "SSN Services"
        await ask_order_confirmation(update, context, display_text, order_description)
        return

    # STEP 5: Info
    if step == "info":
        chosen_type = context.user_data.get("type")

        if chosen_type == "1":  # City
            if not is_valid_name(text):
                await safe_send(update, context, "❌ Invalid city.\nUse letters only.", reply_markup=ssn_nav_kb())
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
                await safe_send(update, context, msg, reply_markup=ssn_nav_kb())
                return
            context.user_data["info"] = canon

        elif chosen_type == "4":  # ZIP
            if not is_valid_zip(text):
                await safe_send(
                    update,
                    context,
                    "❌ Invalid ZIP code.\nUse 5 digits (e.g. 90210) or ZIP+4 (e.g. 90210).",
                    reply_markup=ssn_nav_kb(),
                )
                return
            context.user_data["info"] = text

        else:
            context.user_data["info"] = text

        context.user_data.pop("ssn_step", None)

        display_text = "Order Almost Done!. 🔍"
        order_description = "SSN Services"
        await ask_order_confirmation(update, context, display_text, order_description)
        return
