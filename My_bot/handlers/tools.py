from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from menus.tools_menu import (
    get_tools_inline,
    get_ssn_services_menu,
    get_esim_duration_menu,
)
from menus.orders_menu import get_pending_order_menu
from utils.auto_delete import safe_send
from handlers.orders import ask_order_confirmation
from utils.db import get_pending_order

from utils.validator import (
    is_valid_name,
    is_valid_zip,
    is_valid_dob,
    is_valid_email,
    normalize_us_state_full_name,
    suggest_us_states_full_name,
)

# ---------- UI HELPERS ----------

def ssn_nav_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅ Back", callback_data="ssn_back"),
        InlineKeyboardButton("❌ Cancel", callback_data="cancel_ssn"),
    ]])


def _clear_ssn_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ["ssn_step", "first_name", "last_name", "type", "dob", "info", "from_ssn"]:
        context.user_data.pop(k, None)


def _clear_esim_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for k in ["esim_step", "esim_email", "esim_duration", "esim_country", "custom_price_usd"]:
        context.user_data.pop(k, None)


def _ssn_prev_step(curr: str) -> str | None:
    steps = ["first_name", "last_name", "type", "dob", "info"]
    if curr not in steps:
        return None
    i = steps.index(curr)
    return steps[i - 1] if i > 0 else None


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


def _normalize_dob_input(s: str) -> str:
    s = (s or "").strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s.replace("-", "/")
    return s


# ---------- TOOLS CALLBACK ----------

async def tools_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data.strip()
    user_id = update.effective_user.id

    # Any tool navigation cancels SSN typing mode
    if data.startswith("tool_") and data != "tool_ssn_lookup":
        _clear_ssn_state(context)

    # ---------- RDP ----------
    if data == "tool_rdp":
        _clear_ssn_state(context)
        _clear_esim_state(context)
        await safe_send(
            query,
            context,
            "🖥️ RDP Service\n\nComing soon…",
            reply_markup=get_tools_inline(),
        )
        return

    # ---------- Pending order gate ----------
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

    # ---------- SSN NAV ----------
    if data == "ssn_back":
        step = context.user_data.get("ssn_step")
        prev = _ssn_prev_step(step) if step else None

        if not prev:
            _clear_ssn_state(context)
            await safe_send(query, context, "SSN Services:", reply_markup=get_ssn_services_menu())
            return

        context.user_data["ssn_step"] = prev
        await safe_send(
            query,
            context,
            _prompt_for_step(prev, context.user_data.get("type")),
            reply_markup=ssn_nav_kb(),
        )
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
        duration = data.split(":", 1)[1]
        from pricelist import ESIM_PRICES_USD

        if duration not in ESIM_PRICES_USD:
            await safe_send(query, context, "❌ Invalid duration.", reply_markup=get_esim_duration_menu())
            return

        context.user_data["esim_duration"] = duration
        context.user_data["custom_price_usd"] = ESIM_PRICES_USD[duration]
        context.user_data["esim_step"] = "email"

        await safe_send(query, context, "📧 Enter the email to send your eSIM to:")
        return

    # ---------- Tools menus ----------
    if data == "tool_ssn_services":
        await safe_send(query, context, "SSN Services:", reply_markup=get_ssn_services_menu())
        return

    if data == "tool_back_tools":
        _clear_ssn_state(context)
        _clear_esim_state(context)
        await safe_send(query, context, "Tools:", reply_markup=get_tools_inline())
        return

    if data == "tool_ssn_lookup":
        _clear_ssn_state(context)
        context.user_data["ssn_step"] = "first_name"
        await safe_send(query, context, _prompt_for_step("first_name"), reply_markup=ssn_nav_kb())
        return

    if data == "tool_ssn_magic":
        await safe_send(query, context, "SSN Magic Coming Soon...", reply_markup=get_ssn_services_menu())
        return


# ---------- SSN TEXT FLOW ----------

async def handle_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("ssn_step")
    if not step:
        return

    text = (update.message.text or "").strip()

    if step == "first_name":
        if not is_valid_name(text):
            await safe_send(update, context, "❌ Invalid first name.", reply_markup=ssn_nav_kb())
            return
        context.user_data["first_name"] = text
        context.user_data["ssn_step"] = "last_name"
        await safe_send(update, context, _prompt_for_step("last_name"), reply_markup=ssn_nav_kb())
        return

    if step == "last_name":
        if not is_valid_name(text):
            await safe_send(update, context, "❌ Invalid last name.", reply_markup=ssn_nav_kb())
            return
        context.user_data["last_name"] = text
        context.user_data["ssn_step"] = "type"
        await safe_send(update, context, _prompt_for_step("type"), reply_markup=ssn_nav_kb())
        return

    if step == "type":
        if text not in {"1", "2", "3", "4"}:
            await safe_send(update, context, "❌ Invalid option.", reply_markup=ssn_nav_kb())
            return
        context.user_data["type"] = text
        context.user_data["ssn_step"] = "dob" if text == "2" else "info"
        await safe_send(update, context, _prompt_for_step(context.user_data["ssn_step"], text), reply_markup=ssn_nav_kb())
        return

    if step == "dob":
        dob = _normalize_dob_input(text)
        if not is_valid_dob(dob):
            await safe_send(update, context, "❌ Invalid DOB format.", reply_markup=ssn_nav_kb())
            return
        context.user_data["dob"] = dob
        context.user_data.pop("ssn_step", None)
        await ask_order_confirmation(update, context, "Order Almost Done!. 🔍", "SSN Services")
        return

    if step == "info":
        t = context.user_data.get("type")

        if t == "1" and not is_valid_name(text):
            await safe_send(update, context, "❌ Invalid city.", reply_markup=ssn_nav_kb())
            return

        if t == "3":
            ok, canon = normalize_us_state_full_name(text)
            if not ok:
                s = suggest_us_states_full_name(text)
                msg = "❌ Invalid state."
                if s:
                    msg += "\n\nDid you mean:\n" + "\n".join(f"• {x}" for x in s)
                await safe_send(update, context, msg, reply_markup=ssn_nav_kb())
                return
            text = canon

        if t == "4" and not is_valid_zip(text):
            await safe_send(update, context, "❌ Invalid ZIP code.", reply_markup=ssn_nav_kb())
            return

        context.user_data["info"] = text
        context.user_data.pop("ssn_step", None)
        await ask_order_confirmation(update, context, "Order Almost Done!. 🔍", "SSN Services")


# ---------- eSIM EMAIL TEXT FLOW ----------

async def handle_esim_email_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("esim_step") != "email":
        return

    email = (update.message.text or "").strip()
    if not is_valid_email(email):
        await safe_send(update, context, "❌ Invalid email. Try again.")
        return

    context.user_data["esim_email"] = email
    context.user_data.pop("esim_step", None)

    duration = context.user_data.get("esim_duration")
    amount = context.user_data.get("custom_price_usd", 0)
    pretty = {"1m": "1 Month", "3m": "3 Months", "1y": "1 Year"}.get(duration, duration)

    # Keep "eSIM" at the start so any detection logic still works
    desc = f"eSIM USA - {pretty} | Email: {email}"
 
    text = (
        "Order Almost Done!. 🛜\n\n"
        f"✅ {desc}\n"
        f"📧 Email: {email}\n"
        f"💵 Price: ${amount}"
    )

    await ask_order_confirmation(update, context, text, desc)


