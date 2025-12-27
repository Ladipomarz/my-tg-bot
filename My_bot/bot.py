import os
import sys
import logging

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Logging
logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.INFO)
logger = logging.getLogger(__name__)

# Ensure My_bot folder is on import path
sys.path.insert(0, os.path.dirname(__file__))

from config import BOT_TOKEN
from utils.db import create_tables, expire_pending_order_if_needed
from menus.main_menu import get_main_menu
from menus.orders_menu import get_pending_order_menu
from handlers.start import start, handle_main_menu
from handlers.tools import tools_callback, handle_user_input
from handlers.orders import orders_callback
from handlers.payments import payments_callback


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data
    await query.answer()

    # back to main menu
    if data == "back_main":
        await query.edit_message_text("Back to main menu...")
        await query.message.reply_text("Main menu:", reply_markup=get_main_menu())
        return

    # ✅ Tools / SSN actions (block tools if pending order exists)
    if data.startswith("tool_") or data == "cancel_ssn":
        pending = expire_pending_order_if_needed(query.from_user.id)
        if pending and pending.get("status") == "pending":
            await query.edit_message_text(
                f"🕒 You have a pending order {pending['order_code']}.\nWhat do you want to do?",
                reply_markup=get_pending_order_menu(),
            )
            return

        return await tools_callback(update, context)

    # orders menu callbacks
    if data.startswith("orders_"):
        return await orders_callback(update, context)

    # payments callbacks
    if data.startswith("pay_"):
        return await payments_callback(update, context)


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ✅ Protect SSN flow from crashes + reset if broken
    if context.user_data.get("ssn_step"):
        try:
            await handle_user_input(update, context)
        except Exception:
            logger.exception("SSN flow error")
            # reset so user doesn't get stuck forever
            for key in ["ssn_step", "first_name", "last_name", "type", "dob", "info", "from_ssn"]:
                context.user_data.pop(key, None)
            await update.message.reply_text("❌ Something went wrong. Please start the SSN tool again.")
        return

    await handle_main_menu(update, context)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled exception", exc_info=context.error)


def main():
    create_tables()

    public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    webhook_secret = os.getenv("WEBHOOK_SECRET", "").strip()
    port = int(os.getenv("PORT", "8080"))

    if not public_base_url:
        raise RuntimeError("PUBLIC_BASE_URL is missing (must be your Railway public https URL)")
    if not webhook_secret:
        raise RuntimeError("WEBHOOK_SECRET is missing (set a random string in Railway Variables)")

    url_path = f"webhook/{webhook_secret}"
    webhook_url = f"{public_base_url}/{url_path}"

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_error_handler(on_error)

    print("Bot running (webhook)…")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=url_path,
        webhook_url=webhook_url,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
