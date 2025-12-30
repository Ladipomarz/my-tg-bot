import os
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from payments.plisio import create_plisio_invoice
from utils.db import get_pending_order, set_order_payment
from pricelist import get_price, COIN_MAP, get_plisio_min_usd

logger = logging.getLogger(__name__)


def make_payment_kb(order_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Make Payment", callback_data=f"pay_make:{order_code}")]
    ])


def coin_picker_kb(order_code: str, amount_usd: float) -> InlineKeyboardMarkup:
    # show mins in label if the chosen amount is below the minimum
    def label_for(plisio_code: str, text: str) -> str:
        min_req = get_plisio_min_usd(plisio_code)
        return f"{text} (min ${min_req:g})" if amount_usd < min_req else text

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                label_for("BTC", "₿ BTC"),
                callback_data=f"pay_coin:{order_code}:btc"
            ),
            InlineKeyboardButton("💵 USDT", callback_data=f"pay_usdt:{order_code}"),
        ],
        [
            InlineKeyboardButton(
                label_for("ETH", "Ξ ETH"),
                callback_data=f"pay_coin:{order_code}:eth"
            ),
            InlineKeyboardButton(
                label_for("LTC", "🪙 LTC"),
                callback_data=f"pay_coin:{order_code}:ltc"
            ),
        ],
        [
            InlineKeyboardButton(
                label_for("SOL", "◎ SOL"),
                callback_data=f"pay_coin:{order_code}:sol"
            ),
            InlineKeyboardButton(
                label_for("XMR", "🕵️ XMR"),
                callback_data=f"pay_coin:{order_code}:xmr"
            ),
        ],
        [InlineKeyboardButton("⬅ Back", callback_data=f"pay_back:{order_code}")],
    ])


def usdt_network_kb(order_code: str, amount_usd: float) -> InlineKeyboardMarkup:
    trc_min = get_plisio_min_usd("USDT_TRX")
    erc_min = get_plisio_min_usd("USDT_ETH")

    trc_label = "USDT (TRC20)"
    erc_label = "USDT (ERC20)"
    if amount_usd < trc_min:
        trc_label += f" (min ${trc_min:g})"
    if amount_usd < erc_min:
        erc_label += f" (min ${erc_min:g})"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(trc_label, callback_data=f"pay_coin:{order_code}:usdttrc20"),
            InlineKeyboardButton(erc_label, callback_data=f"pay_coin:{order_code}:usdterc20"),
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
    data = (q.data or "").strip()

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
        await q.edit_message_text(
            "Choose USDT network:",
            reply_markup=usdt_network_kb(order_code, amount_usd),
        )
        return

    if data.startswith("pay_coin:"):
        try:
            _, _, coin_key = data.split(":")
        except ValueError:
            await q.edit_message_text("❌ Invalid selection. Try again.")
            return

        plisio_currency = COIN_MAP.get(coin_key)
        if not plisio_currency:
            await q.edit_message_text("❌ Unknown currency. Try again.")
            return

        min_required = get_plisio_min_usd(plisio_currency)
        if amount_usd < min_required:
            # return to same UX and show mins on buttons
            if coin_key.startswith("usdt"):
                await q.edit_message_text(
                    f"❌ Minimum for {plisio_currency} is ${min_required:.2f}.\nChoose another option.",
                    reply_markup=usdt_network_kb(order_code, amount_usd),
                )
            else:
                await q.edit_message_text(
                    f"❌ Minimum for {plisio_currency} is ${min_required:.2f}.\nChoose another coin.",
                    reply_markup=coin_picker_kb(order_code, amount_usd),
                )
            return

        public_base = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
        if not public_base:
            await q.edit_message_text("❌ PUBLIC_BASE_URL missing on Railway.")
            return

        try:
            await q.edit_message_text("Creating payment link…")

            invoice_url = await create_plisio_invoice(
                order_number=order_code,  # IMPORTANT: webhook uses this to find the order
                order_name=f"SSN Service {order_code}",
                amount_usd=amount_usd,
                crypto_currency=plisio_currency,
                callback_url=f"{public_base}/webhooks/plisio",
                success_url=f"https://t.me/{context.bot.username}",
                fail_url=f"https://t.me/{context.bot.username}",
            )

            # Store payment data (provider/status fields supported by updated db.py)
            set_order_payment(
                pending["id"],
                invoice_url=invoice_url,
                pay_currency=plisio_currency,
                pay_provider="plisio",
                pay_status="pending",
            )

            await q.edit_message_text(
                f"✅ Payment link created\n"
                f"Order: {order_code}\n"
                f"Amount: ${amount_usd:.2f}\n"
                f"Currency: {plisio_currency}\n\n"
                f"Tap below to open payment page:",
                reply_markup=open_invoice_kb(invoice_url),
            )

        except Exception as e:
            logger.exception("Plisio invoice creation failed")
            await q.edit_message_text(
                f"❌ Failed to create payment link:\n{e}\n\nChoose another coin.",
                reply_markup=coin_picker_kb(order_code, amount_usd),
            )
