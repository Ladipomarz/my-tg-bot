import os
print("DEBUG payments dir exists:", os.path.exists(os.path.join(os.path.dirname(os.path.dirname(__file__)), "payments")))
print("DEBUG nowpayments exists:", os.path.exists(os.path.join(os.path.dirname(os.path.dirname(__file__)), "payments", "nowpayments.py")))


from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
import os, sys

BASE_DIR = os.path.dirname(os.path.dirname(__file__))  # .../My_bot
sys.path.insert(0, BASE_DIR)

from payments.nowpayments import create_invoice



def make_payment_kb(order_code: str):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💳 Make Payment", callback_data=f"pay_make:{order_code}")
    ]])


async def show_make_payment(update_or_query, context: ContextTypes.DEFAULT_TYPE, order_code: str):
    # Works for either a Message or a CallbackQuery
    if getattr(update_or_query, "callback_query", None):
        q = update_or_query.callback_query
        await q.edit_message_text("Tap below to pay:", reply_markup=make_payment_kb(order_code))
    else:
        await update_or_query.message.reply_text("Tap below to pay:", reply_markup=make_payment_kb(order_code))


async def payments_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if not data.startswith("pay_make:"):
        return

    order_code = data.split(":", 1)[1]

    await q.edit_message_text("Creating payment link…")

    invoice_id, invoice_url = await create_invoice(
        order_code=order_code,
        description=f"Digital service order {order_code}",
        amount_usd=10.0,  # change later
    )

    await q.edit_message_text(
        f"✅ Payment link created for {order_code}\n"
        f"Invoice: {invoice_id}\n\n"
        f"Open and pay:\n{invoice_url}"
    )
