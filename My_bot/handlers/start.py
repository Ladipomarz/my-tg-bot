from telegram import Update
from telegram.ext import ContextTypes

from utils.db import add_user, expire_pending_order_if_needed
from menus.main_menu import get_main_menu
from menus.orders_menu import get_pending_order_menu

from handlers.tools import open_tools_menu
from handlers.wallet import open_wallet
from handlers.referral import open_referral
from handlers.orders import open_orders_menu
from config import ADMIN_IDS


def _norm_menu_text(t: str) -> str:
    """
    Normalizes reply-keyboard text so changes like 'Orders' vs 'orders'
    or removing emojis won't break routing.
    """
    t = (t or "").strip().lower()

    # remove common emojis + extra spaces
    for ch in ["🧰", "🛒", "👤", "💵"]:
        t = t.replace(ch, "")
    t = " ".join(t.split())
    return t


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    add_user(
        user_id=user.id,
        first_name=user.first_name,
        username=user.username,
    )

    admin_badge = " (Admin)" if user.id in ADMIN_IDS else ""

    await update.message.reply_text(
        f"Hello {user.first_name}{admin_badge}! Welcome to your underground bot.",
        reply_markup=get_main_menu(),
    )


async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = (update.message.text or "")
    text = _norm_menu_text(raw_text)

    print("user tapped:", repr(raw_text), "->", repr(text))

    # If SSN flow active, DO NOT open menus
    if context.user_data.get("ssn_step"):
        return

    # ✅ Tools gate happens HERE (because ReplyKeyboard sends text)
    if text == "🧰Tools":
        pending = expire_pending_order_if_needed(update.effective_user.id)
        if pending and pending.get("status") == "pending":
            await update.message.reply_text(
                f"🕒 You have a pending order {pending['order_code']}.\nWhat do you want to do?",
                reply_markup=get_pending_order_menu(),
            )
            return
        return await open_tools_menu(update, context)

    if text == "🛒 Orders":
        return await open_orders_menu(update, context)

    await update.message.reply_text("Unknown command, please use menu buttons.")
