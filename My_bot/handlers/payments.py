from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from payments.nowpayments import create_invoice
import logging

logger = logging.getLogger(__name__)


def make_payment_kb(order_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💳 Make Payment", callback_data=f"pay_make:{order_code}")
    ]])


def open_invoice_kb(invoice_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔗 Open payment page", url=invoice_url)
    ]])


async def show_make_payment(update_or_query, context: ContextTypes.DEFAULT_TYPE, order_code: str):
    if getattr(update_or_query, "callback_query", None):
        q = update_or_query.callback_query
        await q.edit_message_text("Tap below to pay:", reply_markup=make_payment_kb(order_code))
    else:
        await update_or_query.message.reply_text("Tap below to pay:", reply_markup=make_payment_kb(order_code))


async def payments_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""

    if not data.startswith("pay_make:"):
        return

    order_code = data.split(":", 1)[1]

    await q.edit_message_text("Creating payment link…")

    try:
        invoice_id, invoice_url = await create_invoice(
            order_code=order_code,
            description=f"Digital service order {order_code}",
            amount_usd=7.0,  # change later
        )
    except Exception:
        logger.exception("Create invoice failed")
        await q.edit_message_text("❌ Failed to create payment link. Please try again.")
        return

    await q.edit_message_text(
        f"✅ Payment link created for {order_code}\n"
        f"Invoice: {invoice_id}\n\n"
        f"Tap the button below to open and pay:",
        reply_markup=open_invoice_kb(invoice_url),
    )
