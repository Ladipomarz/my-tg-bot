import os
import sys
import logging

# Configure logging first
logging.basicConfig(level=logging.INFO)

# Reduce noisy poll logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.INFO)  # set to WARNING if you want quieter

from telegram import Update
from telegram.error import Conflict
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Ensure My_bot folder is on import path (script-style project)
sys.path.insert(0, os.path.dirname(__file__))

from config import BOT_TOKEN
from utils.db import create_tables
from menus.main_menu import get_main_menu
from handlers.start import start, handle_main_menu
from handlers.tools import tools_callback, handle_user_input  # SSN
from handlers.orders import orders_callback
from handlers.payments import payments_callback

logger = logging.getLogger(__name__)


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data
    await query.answer()

    if data == "back_main":
        await query.edit_message_text("Back to main menu...")
        await query.message.reply_text("Main menu:", reply_markup=get_main_menu())
        return

    if data.startswith("tool_") or data == "cancel_ssn":
        return await tools_callback(update, context)

    if data.startswith("orders_"):
        return await orders_callback(update, context)

    if data.startswith("pay_"):
        return await payments_callback(update, context)


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("ssn_step"):
        await handle_user_input(update, context)
        return

    await handle_main_menu(update, context)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # This removes the "No error handlers are registered" message and logs real exceptions
    logger.exception("Unhandled exception", exc_info=context.error)


def main():
    create_tables()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    # Register error handler
    app.add_error_handler(on_error)

    print("Bot running…")

    try:
        app.run_polling(drop_pending_updates=True)
    except Conflict:
        # If another instance is polling (deploy overlap), exit cleanly.
        raise SystemExit(0)


if __name__ == "__main__":
    main()