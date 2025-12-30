from telegram import Update
from telegram.ext import ContextTypes

from utils.db import add_user
from menus.main_menu import get_main_menu
from handlers.tools import open_tools_menu
from handlers.wallet import open_wallet
from handlers.referral import open_referral
from handlers.orders import open_orders_menu
from config import ADMIN_IDS


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # ✅ store user safely
    add_user(
        user_id=user.id,
        first_name=user.first_name,
        username=user.username,
    )

    admin_badge = " (Admin)" if user.id in ADMIN_IDS else ""

    await update.message.reply_text(
        f"Hello {user.id}{admin_badge}! Welcome to your underground bot.",
        reply_markup=get_main_menu()
    )


async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    print("user tapped:", repr(text))

    if context.user_data.get("ssn_step"):
        return

    if text == "🧰 Tools":
        return await open_tools_menu(update, context)

    if text == "🛒 Orders":
        return await open_orders_menu(update, context)

    if text == "💵 Wallet":
        return await open_wallet(update, context)

    if text == "👤 Referral":
        return await open_referral(update, context)

    await update.message.reply_text("Unknown command, please use menu buttons.")
