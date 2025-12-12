from telegram import Update
from telegram.ext import ContextTypes
from menus.wallet_menu import get_wallet_menu

async def open_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Wallet Menu:",
        reply_markup=get_wallet_menu()
    )