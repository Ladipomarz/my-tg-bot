import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from payments.nowpayments import create_invoice
from utils.db import get_pending_order, set_order_payment
from pricelist import get_price

logger = logging.getLogger(__name__)

BTC_MIN_USD = 20.0


def make_payment_kb(order_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Make Payment", callback_data=f"pay_make:{order_code}")]
    ])


def coin_picker_kb(order_code: str, amount_usd: float) -> InlineKeyboardMarkup:
    btc_label = "₿ BTC"
    if amount_usd < BTC_MIN_USD:
        btc_label = "₿ BTC (min $20)"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(btc_label, callback_data=f"pay_coin:{order_code}:btc"),
            InlineKeyboardButton("💵 USDT", callback_data=f"pay_usdt:{order_code}"),
        ],
        [
            InlineKeyboardButton("Ξ ETH", callback_data=f"pay_coin:{order_code}:eth"),
            InlineKeyboardButton("🪙 LTC", callback_data=f"pay_coin:{order_code}:ltc"),
        ],
        [
            InlineKeyboardButton("◎ SOL", callback_data=f"pay_coin:{order_code}:sol"),
            InlineKeyboardButton("🕵️ XMR", callback_data=f"pay_coin:{order_code}:xmr"),
        ],
        [InlineKeyboardButton("⬅ Back", callback_data=f"pay_back:{order_code}")],
    ])


def usdt_network_kb(order_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("USDT (TRC20)", callback_data=f"pay_coin:{order_code}:usdttrc20"),
            InlineKeyboardButton("USDT (ERC20)", callback_data=f"pay_coin:{order_code}:usdterc20"),
        ],
        [InlineKeyboardButton("⬅ Back", callback_data=f"pay_make:{order_code}")],
    ])


def open_invoice_kb(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Open payment page", url=url)]])


async def show_make_payment(update_or_query, context: ContextTypes.DEFAULT_TYPE, order_code: str):
    if getattr(update_or_query, "callback_query", None):
        q = update_or_query.callback_query
        await q.edit_message_text("Tap below to pay:", reply_markup=make_payment_kb(order_code))
    else:
        await update_or_query.message.reply_text("Tap below to pay:", reply_markup=make_payment_kb(order_code))


async def payments_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    pending = get_pending_order(q.from_user.id)
    if not pending:
        await q.edit_message_text("❌ No pending order.")
        return

    amount_usd = get_price("ssn")  # SSN only for now
    order_code = pending["order_code"]

    if data.startswith("pay_back:"):
        await q.edit_message_text("Tap below to pay:", reply_markup=make_payment_kb(order_code))
        return

    if data.startswith("pay_make:"):
        await q.edit_message_text(
            f"Choose a payment currency:\nAmount: ${amount_usd:.2f}",
            reply_markup=coin_picker_kb(order_code, amount_usd),
        )
        return

    if data.startswith("pay_usdt:"):
        await q.edit_message_text("Choose USDT network:", reply_markup=usdt_network_kb(order_code))
        return

    if data.startswith("pay_coin:"):
        _, _, currency = data.split(":")

        if currency == "btc" and amount_usd < BTC_MIN_USD:
            await q.edit_message_text(
                "₿ Bitcoin is available only for orders $20+.\nPlease choose another coin.",
                reply_markup=coin_picker_kb(order_code, amount_usd),
            )
            return

        try:
            await q.edit_message_text("Creating payment link…")

            invoice_id, invoice_url = await create_invoice(
                order_code=order_code,
                description=f"SSN Service {order_code}",
                amount_usd=amount_usd,
                pay_currency=currency,
            )

            set_order_payment(pending["id"], invoice_url=invoice_url, pay_currency=currency)

            await q.edit_message_text(
                f"✅ Payment link created\n"
                f"Order: {order_code}\n"
                f"Amount: ${amount_usd:.2f}\n"
                f"Currency: {currency.upper()}\n\n"
                f"Tap below to open payment page:",
                reply_markup=open_invoice_kb(invoice_url),
            )

        except Exception:
            logger.exception("Invoice creation failed")
            await q.edit_message_text(
                "❌ Failed to create payment link.\nChoose another coin.",
                reply_markup=coin_picker_kb(order_code, amount_usd),
            )

