from telegram import Update
from telegram.ext import ContextTypes
from menus.referral_menu import get_referral_menu


async def open_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Referral Menu:",
        reply_markup=get_referral_menu()
    )