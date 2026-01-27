import os
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from payments.plisio import create_plisio_invoice
from utils.db import get_pending_order, set_order_payment,expire_pending_order_if_needed,update_order_status
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
        [InlineKeyboardButton("🔗 Open payment page", url=str(invoice_url))]
    ])



def open_invoice_cancel_kb(invoice_url: str, order_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Open payment page", url=str(invoice_url))],
        [InlineKeyboardButton("🗑 Cancel & create new", callback_data=f"pay_cancel:{order_code}")],
    ])
  

async def safe_edit(q, text: str, reply_markup=None, **kwargs):
    try:
        await q.edit_message_text(text, reply_markup=reply_markup, **kwargs)
    except BadRequest as e:
        msg = str(e).lower()
        # ignore harmless edit errors
        if "message is not modified" in msg:
            return
        if "message can't be edited" in msg:
            # fallback: send a new message
            await q.message.reply_text(text, reply_markup=reply_markup, **kwargs)
            return
        raise


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
     
    logger.info("coin_picker_kb resolved to: %r", coin_picker_kb)
    q = update.callback_query
    await q.answer()

    data = (q.data or "").strip()

    # Fetch pending order
    pending = get_pending_order(q.from_user.id)
    if not pending:
        await q.edit_message_text("❌ No pending order.")
        return
   
    # Expire ONLY if expires_at says so
    chk = expire_pending_order_if_needed(q.from_user.id)
    if chk and chk.get("status") == "expired":
        await q.edit_message_text("⚠️ Your previous order expired. Please create a new order.")
        return

    order_code = pending["order_code"]
    desc = (pending.get("description") or "").strip() or "Service"
    order_type = (pending.get("order_type") or "").lower().strip()

    # Determine amount
    if order_type == "wallet_topup":
        amount_usd = _safe_float(pending.get("amount_usd"))
    else:
        amount_usd = _resolve_amount_usd(context, pending)

    if amount_usd is None:
        await safe_edit(q,
            "❌ Could not determine price for this order.\nPlease restart the order and try again.",
            )
        
        return
    
    expires_at = pending.get("expires_at")
    remaining = None
    if expires_at:
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
            
        now = datetime.now(timezone.utc)
        remaining = int((expires_at - now).total_seconds())    
        if remaining < 0:
            remaining = 0
        
        
        existing_url = (pending.get("invoice_url") or "").strip()
        existing_status = (pending.get("pay_status") or "").lower().strip()
        

        # If invoice already exists and still usable, reuse it
        if existing_url and existing_status in {"pending", "processing", "detected"}:
            if order_type == "wallet_topup" and remaining and remaining > 0:
                await q.edit_message_text( 
                    f"✅ You already have an active top up.\n"
                    f"⏳ Time left: {remaining//60} min\n\n"
                    f"Tap below to continue or cancel and create a new top up.",
                    reply_markup=open_invoice_cancel_kb(existing_url, order_code), 
                      
                )
                return
            
            
            
            await q.edit_message_text(
                "✅ Payment link already created.\nTap below to open it:",
                reply_markup=open_invoice_kb(existing_url),
            )
            return
        
          
        # fallback for non-topup orders
        if not existing_url:
            await q.edit_message_text("❌ Missing payment link. Please create a new top up.")
            return

    # ---- ROUTING: handle the pressed button ----
    if data.startswith("pay_back:"):
        await q.edit_message_text("Tap below to pay:", reply_markup=make_payment_kb(order_code))
        return

    if data.startswith("pay_make:"):
        
        kb = coin_picker_kb(order_code, amount_usd)
        logger.info("pay_make keyboard=%r", kb.to_dict())
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
    
    if data.startswith("pay_cancel:"):
        update_order_status(pending["id"], "cancelled")
        await q.edit_message_text("✅ Top up cancelled. Now create a new top up.")
        return

    
    if data.startswith("pay_coin:"):
        # Expected: pay_coin:<order_code>:<coin_key>
        try:
            _, _, coin_key = data.split(":")
        except ValueError:
            await q.edit_message_text("❌ Invalid selection. Try again.")
            return
        

        plisio_currency = COIN_MAP.get(coin_key)
        if not plisio_currency:
            await q.edit_message_text("❌ Unknown currency. Try again.")
            return

        # Min checks
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
                 f"⏳ Time left: {remaining//60} min\n\n"
                f"Tap below to open payment page:",
                reply_markup=open_invoice_kb(invoice_url,order_code),
            )
            return  # ✅ CRITICAL: prevent falling into Unknown action

        except Exception as e:
            logger.exception("Plisio invoice creation failed: %s", str(e))
            msg = str(e)

            if "Invoice with the same order_number already exists" in msg or "return_existing" in msg:
                await q.edit_message_text(
                    "⚠️ Payment link already exists for this order.\nTap below to continue:",
                    reply_markup=make_payment_kb(order_code),
                )
                return

            await q.edit_message_text(
                f"❌ Failed to create payment link:\n{e}\n\nChoose another coin.",
                reply_markup=coin_picker_kb(order_code, amount_usd),
            )
            return

    # Unknown callback
    await q.edit_message_text("❌ Unknown action. Please try again.")
