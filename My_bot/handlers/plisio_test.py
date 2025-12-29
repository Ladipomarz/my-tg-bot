import time
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from payments.plisio import create_plisio_invoice

PUBLIC_BASE = "https://my-tg-bot-production-9a75.up.railway.app"
SUCCESS_URL = "https://t.me/thejuicybox_bot"
FAIL_URL = "https://t.me/thejuicybox_bot"


async def test_plisio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text("Creating Plisio BTC $1 invoice…")

    try:
        invoice_url = await create_plisio_invoice(
            order_number=f"PLISIO-{user.id}-{int(time.time())}",
            amount_usd=1.00,
            crypto_currency="BTC",
            callback_url=f"{PUBLIC_BASE}/webhooks/plisio",
            success_url=SUCCESS_URL,
            fail_url=FAIL_URL,
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error:\n{e}")
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💸 Pay BTC ($1)", url=invoice_url)]
    ])

    await update.message.reply_text("✅ Invoice created:", reply_markup=kb)
