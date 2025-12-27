from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from payments.nowpayments import create_invoice
import logging

logger = logging.getLogger(__name__)

# --- CONFIG: your supported currencies ---
PAY_BTC = "btc"
PAY_ETH = "eth"
PAY_LTC = "ltc"
PAY_SOL = "sol"
PAY_XMR = "xmr"
PAY_USDT_TRC20 = "usdttrc20"
PAY_USDT_ERC20 = "usdterc20"


def make_payment_kb(order_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💳 Make Payment", callback_data=f"pay_make:{order_code}")
    ]])


def coin_picker_kb(order_code: str) -> InlineKeyboardMarkup:
    # Pretty 2-column layout
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("₿ BTC", callback_data=f"pay_coin:{order_code}:{PAY_BTC}"),
            InlineKeyboardButton("💵 USDT", callback_data=f"pay_usdt_net:{order_code}"),
        ],
        [
            InlineKeyboardButton("Ξ ETH", callback_data=f"pay_coin:{order_code}:{PAY_ETH}"),
            InlineKeyboardButton("🪙 LTC", callback_data=f"pay_coin:{order_code}:{PAY_LTC}"),
        ],
        [
            InlineKeyboardButton("◎ SOL", callback_data=f"pay_coin:{order_code}:{PAY_SOL}"),
            InlineKeyboardButton("🕵️ XMR", callback_data=f"pay_coin:{order_code}:{PAY_XMR}"),
        ],
        [
            InlineKeyboardButton("⬅️ Back", callback_data=f"pay_back:{order_code}")
        ]
    ])


def usdt_network_kb(order_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("USDT (TRC20) ✅", callback_data=f"pay_coin:{order_code}:{PAY_USDT_TRC20}"),
            InlineKeyboardButton("USDT (ERC20)", callback_data=f"pay_coin:{order_code}:{PAY_USDT_ERC20}"),
        ],
        [
            InlineKeyboardButton("⬅️ Back", callback_data=f"pay_make:{order_code}")
        ]
    ])


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


async def _create_locked_invoice(
    *,
    q,
    order_code: str,
    amount_usd: float,
    pay_currency: str,
):
    await q.edit_message_text(f"Creating {pay_currency.upper()} payment link…")

    invoice_id, invoice_url = await create_invoice(
        order_code=order_code,
        description=f"Digital service order {order_code}",
        amount_usd=amount_usd,
        pay_currency=pay_currency,  # ✅ lock currency => persistent wallet page
    )

    await q.edit_message_text(
        f"✅ Payment link created\n"
        f"Order: {order_code}\n"
        f"Amount: ${amount_usd:.2f}\n"
        f"Currency: {pay_currency.upper()}\n"
        f"Invoice: {invoice_id}\n\n"
        f"Tap below to open and pay:",
        reply_markup=open_invoice_kb(invoice_url),
    )


async def payments_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = (q.data or "").strip()

    # ---- SET YOUR PRICE HERE (later you will pull from pricelist/db) ----
    amount_usd = 13.00

    # 1) user clicked "Make Payment"
    if data.startswith("pay_make:"):
        order_code = data.split(":", 1)[1]
        await q.edit_message_text(
            "Choose a payment currency:",
            reply_markup=coin_picker_kb(order_code),
        )
        return

    # back to first step
    if data.startswith("pay_back:"):
        order_code = data.split(":", 1)[1]
        await q.edit_message_text("Tap below to pay:", reply_markup=make_payment_kb(order_code))
        return

    # 2) user clicked "USDT" => ask network
    if data.startswith("pay_usdt_net:"):
        order_code = data.split(":", 1)[1]
        await q.edit_message_text(
            "Choose USDT network:",
            reply_markup=usdt_network_kb(order_code),
        )
        return

    # 3) user picked a specific coin (including USDTTRC20/USDTERC20)
    if data.startswith("pay_coin:"):
        _, order_code, pay_currency = data.split(":", 2)

        try:
            await _create_locked_invoice(
                q=q,
                order_code=order_code,
                amount_usd=amount_usd,
                pay_currency=pay_currency,
            )
        except Exception:
            logger.exception("Create invoice failed")
            await q.edit_message_text(
                "❌ Failed to create payment link for that currency.\n"
                "Please choose a different coin/network.",
                reply_markup=coin_picker_kb(order_code),
            )
        return
