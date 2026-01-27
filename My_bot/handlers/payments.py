import os
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from payments.plisio import create_plisio_invoice
from utils.db import get_pending_order, set_order_payment,expire_pending_order_if_needed
from pricelist import get_price, COIN_MAP, get_plisio_min_usd
from datetime import datetime, timedelta,timezone

logger = logging.getLogger(__name__)


def make_payment_kb(order_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Make Payment", callback_data=f"pay_make:{order_code}")]
    ])


def coin_picker_kb(order_code: str, amount_usd: float) -> InlineKeyboardMarkup:
    def label_for(plisio_code: str, text: str) -> str:
        min_req = get_plisio_min_usd(plisio_code)
        return f"{text} (min ${min_req:g})" if amount_usd < min_req else text

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(label_for("BTC", "₿ BTC"), callback_data=f"pay_coin:{order_code}:btc"),
            InlineKeyboardButton("💵 USDT", callback_data=f"pay_usdt:{order_code}"),
        ],
        [
            InlineKeyboardButton(label_for("ETH", "Ξ ETH"), callback_data=f"pay_coin:{order_code}:eth"),
            InlineKeyboardButton(label_for("LTC", "🪙 LTC"), callback_data=f"pay_coin:{order_code}:ltc"),
        ],
        [
            InlineKeyboardButton(label_for("SOL", "◎ SOL"), callback_data=f"pay_coin:{order_code}:sol"),
            InlineKeyboardButton(label_for("XMR", "🕵️ XMR"), callback_data=f"pay_coin:{order_code}:xmr"),
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


def open_invoice_kb(invoice_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Open payment page", url=invoice_url)]
    ])


async def show_make_payment(update_or_query, context: ContextTypes.DEFAULT_TYPE, order_code: str):
    if getattr(update_or_query, "callback_query", None):
        q = update_or_query.callback_query
        await q.edit_message_text("Tap below to pay:", reply_markup=make_payment_kb(order_code))
    else:
        await update_or_query.message.reply_text("Tap below to pay:", reply_markup=make_payment_kb(order_code))


def _safe_float(v):
    """Convert v to float safely; return None if impossible."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _resolve_amount_usd(context: ContextTypes.DEFAULT_TYPE, pending: dict) -> float | None:
    """
    Priority:
      1) context.user_data['custom_price_usd'] (eSIM flow)
      2) fallback to MSN default from pricelist
    """
    # 1) eSIM custom override
    custom = _safe_float(context.user_data.get("custom_price_usd"))
    if custom is not None and custom > 0:
        return custom

    # 2) fallback: MSN default
    # (adjust the key below if your pricelist uses a different key)
    try:
        msn_price = get_price("msn")
        msn_price = _safe_float(msn_price)
        if msn_price is not None and msn_price > 0:
            return msn_price
    except Exception:
        logger.exception("Failed to get MSN default price via get_price('msn')")

    # If you store price in DB pending (optional), try these keys too:
    for k in ("amount_usd", "price_usd", "usd_amount"):
        dbv = _safe_float(pending.get(k))
        if dbv is not None and dbv > 0:
            return dbv

    return None



# Modify the function to check and expire pending orders after 1 minute
async def payments_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    data = (q.data or "").strip()
    
    # Fetch pending order
    pending = get_pending_order(q.from_user.id)
    if not pending:
        await q.edit_message_text("❌ No pending order.")
        return

    order_code = pending["order_code"]
    
    # Get order type and amount
    order_type = (pending.get("order_type") or "").lower().strip()
    if order_type == "wallet_topup":
        amount_usd = _safe_float(pending.get("amount_usd"))
    else:
        amount_usd = _resolve_amount_usd(context, pending)
    
    # Check if there's an existing invoice URL and its status
    existing_url = (pending.get("invoice_url") or "").strip()
    existing_status = (pending.get("pay_status") or "").lower().strip()

    # Ensure 'order_created_at' is valid and parse the date
    order_created_at = pending.get("created_at")

    if order_created_at:
        # psycopg often returns a real datetime, not a string
        if isinstance(order_created_at, datetime):
            created_at = order_created_at
        else:
            # if it ever comes as string
            created_at = datetime.fromisoformat(str(order_created_at))

        # normalize timezone to avoid naive/aware issues
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)

        if now - created_at > timedelta(minutes=1):
            expire_pending_order_if_needed(q.from_user.id)
            await q.edit_message_text(
                "⚠️ Your previous order expired (pending too long). Please create a new order."
            )
            return

    
    # If an invoice URL exists and the order status is still 'pending' or 'processing'
    if existing_url and existing_status in {"pending", "processing", "detected"}:
        await q.edit_message_text(
            f"✅ Payment link already created for this order.\n"
            f"Order: {order_code}\n"
            f"Amount: ${amount_usd:.2f}\n"
            f"Currency: {pending.get('pay_currency') or '—'}\n\n"
            f"Tap below to open payment page:",
            reply_markup=open_invoice_kb(existing_url),
        )
        return
    
    # If there's no invoice, we proceed to create a new one
    logger.info(f"Proceeding to create a new invoice for order {order_code}")
    # Add logic to create invoice here


    # Use description for nicer invoice title
    desc = (pending.get("description") or "").strip() or "Service"
    
    order_type = (pending.get("order_type") or "").lower().strip()

    # Proceed to create a new invoice if no existing invoice
    if order_type == "wallet_topup":
        # Wallet topups must always use DB amount, never custom_price_usd/MSN price
        amount_usd = _safe_float(pending.get("amount_usd"))
    else:
        amount_usd = _resolve_amount_usd(context, pending)

    if amount_usd is None:
        await q.edit_message_text(
            "❌ Could not determine price for this order.\n"
            "Please restart the order and try again."
        )
        return

    try:
        # Creating a new payment invoice if no existing one is found
        inv = await create_plisio_invoice(
            order_number=order_code,
            order_name=f"{desc} {order_code}",
            amount_usd=amount_usd,
            crypto_currency="usdt",  # Adjust this part if your user selects a different coin
            callback_url=f"{public_base}/webhooks/plisio",  # You should have public_base configured
            success_url=f"https://t.me/{context.bot.username}",
            fail_url=f"https://t.me/{context.bot.username}",
        )

        invoice_url = inv["invoice_url"] if isinstance(inv, dict) else inv
        set_order_payment(
            pending["id"],
            invoice_url=invoice_url,
            pay_currency="USDT",  # You can dynamically use the selected currency
            pay_provider="plisio",
            pay_status="pending",
        )

        # Sending the link for payment
        await q.edit_message_text(
            f"✅ Payment link created\n"
            f"Order: {order_code}\n"
            f"Amount: ${amount_usd:.2f}\n"
            f"Currency: USDT\n\n"
            f"Tap below to open payment page:",
            reply_markup=open_invoice_kb(invoice_url),
        )

    except Exception as e:
        logger.exception("Plisio invoice creation failed")
        await q.edit_message_text(
            f"❌ Failed to create payment link:\n{e}\n\nChoose another coin.",
            reply_markup=coin_picker_kb(order_code, amount_usd),
        )
        return


    

    if amount_usd is None:
        await q.edit_message_text(
            "❌ Could not determine price for this order.\n"
            "Please restart the order and try again."
        )
        return

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

            inv = await create_plisio_invoice(
                order_number=order_code,
                order_name=f"{desc} {order_code}",
                amount_usd=amount_usd,
                crypto_currency=plisio_currency,
                callback_url=f"{public_base}/webhooks/plisio",
                success_url=f"https://t.me/{context.bot.username}",
                fail_url=f"https://t.me/{context.bot.username}",
            )

            invoice_url = inv["invoice_url"] if isinstance(inv, dict) else inv

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
            # Log the exception to understand the error message structure
            logger.exception("Plisio invoice creation failed: %s", str(e))

            # Get the error message, or use a fallback if it's not present
            msg = str(e) if hasattr(e, 'message') and e.message else str(e)

            # ✅ Plisio duplicate invoice: don't keep trying to create again
            if "Invoice with the same order_number already exists" in msg or "return_existing" in msg:
                await q.edit_message_text(
                    "⚠️ Payment link already exists for this order.\n"
                    "Tap below to continue:",
                    reply_markup=make_payment_kb(order_code),
                )
                return

            # Handle any other errors
            await q.edit_message_text(
                f"❌ Failed to create payment link:\n{e}\n\nChoose another coin.",
                reply_markup=coin_picker_kb(order_code, amount_usd),
            )
            return


    # If some unknown callback comes in
    await q.edit_message_text("❌ Unknown action. Please try again.")
