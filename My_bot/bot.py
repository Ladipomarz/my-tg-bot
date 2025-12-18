from telegram import Update
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from handlers.payments import payments_callback
from config import BOT_TOKEN
from utils.db import create_tables
from handlers.start import start, handle_main_menu
from handlers.tools import tools_callback, handle_user_input  # SSN
from handlers.orders import orders_callback
from menus.main_menu import get_main_menu
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)



async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    await query.answer()

    # back to main menu
    if data == "back_main":
        await query.edit_message_text("Back to main menu...")
        await query.message.reply_text("Main menu:", reply_markup=get_main_menu())
        return

    # tools menu + cancel SSN
    if data.startswith("tool_") or data == "cancel_ssn":
        return await tools_callback(update, context)

    # orders menu callbacks
    if data.startswith("orders_"):
        return await orders_callback(update, context)
    
    if data.startswith("pay_"):
        return await payments_callback(update, context)



async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Route all plain text messages based on active flow.
    Priority:
    - SSN flow
    - (Future) Orders flow
    - Otherwise: main menu
    """
    if context.user_data.get("ssn_step"):
        await handle_user_input(update, context)   # SSN flow
        return

    # No orders_step yet (no text-based order form), so we go straight to main menu
    await handle_main_menu(update, context)


def main():
    create_tables()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # /start command
    app.add_handler(CommandHandler("start", start))

    # inline buttons
    app.add_handler(CallbackQueryHandler(callback_router))

    # text messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    print("Bot running…")
    app.run_polling()


if __name__ == "__main__":
    main()
