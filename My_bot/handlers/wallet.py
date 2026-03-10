from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from handlers.payments import show_make_payment, open_invoice_cancel_kb, make_payment_kb


from utils.db import (
    create_order,
    expire_pending_order_if_needed,
    get_pending_order,
)
from utils.auto_delete import safe_send


def _fmt_usd(x) -> str:
    try:
        return f"${Decimal(str(x)):.2f}"
    except Exception:
        return f"${x}"


def _seconds_left_from_expires_at(expires_at) -> int:
    if not expires_at:
        return 0

    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except Exception:
            return 0

    if getattr(expires_at, "tzinfo", None) is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    return max(0, int((expires_at - now).total_seconds()))


def _fmt_left(seconds: int) -> str:
    m, s = divmod(max(0, seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m"
    return f"{s}s"


async def _show_existing_topup_or_continue(update: Update, context: ContextTypes.DEFAULT_TYPE, pending: dict) -> bool:
    """
    Returns True if it handled the flow (pending exists),
    False if caller should proceed with 'ask for amount / create order'.
    """
    if not pending or (pending.get("order_type") or "").lower() != "wallet_topup":
        return False

    secs_left = _seconds_left_from_expires_at(pending.get("expires_at"))
    if secs_left <= 0:
        return False

    invoice_url = (pending.get("invoice_url") or "").strip()
    order_code = pending.get("order_code")
    amount = pending.get("amount_usd")
    currency = (pending.get("pay_currency") or "Not chosen").upper()

   
    # Prefer replying on message if available (callback vs text)
    msg_target = update.callback_query.message if update.callback_query else update.message
    if not msg_target:
        return False

    if invoice_url:
        await msg_target.reply_text(
            "✅ You already have an active top up.\n"
            f"Order: {order_code}\n"
            f"Amount: ${float(amount):.2f}\n"
            f"Currency: {currency}\n"
            f"⏳ Time left: {_fmt_left(secs_left)}\n\n"
            "Tap below to continue or cancel and create a new top up.",
            reply_markup=open_invoice_cancel_kb(invoice_url, order_code),
        )
        return True

    # No invoice yet -> send them to payment menu (coin selection happens in payments.py)
    await msg_target.reply_text(
        "✅ You already started a top up.\n"
        f"⏳ Time left: {_fmt_left(secs_left)}\n\n"
        "Continue to payment:",
        reply_markup=make_payment_kb(order_code),
    )
    return True


async def wallet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()

    user_id = update.effective_user.id

    if q.data == "back_main":
        await q.message.reply_text("⬅ Back. Use the main menu buttons below.")
        return

    if q.data == "wallet_topup":
        # 1) Expire old pending orders
        expire_pending_order_if_needed(user_id)

        # 2) If active topup exists -> show link+cancel (or continue-to-payment)
        pending = get_pending_order(user_id)
        handled = await _show_existing_topup_or_continue(update, context, pending)
        if handled:
            context.user_data.pop("wallet_step", None)
            return

        # 3) Otherwise ask for amount
        context.user_data["wallet_step"] = "await_amount"
        context.user_data.pop("otp_step", None)
        msg = await safe_send(
            update,
            context,
            "💳 <b>Top up Wallet</b>\n\nEnter the amount in USD (example: <b>10</b>).",
            parse_mode="HTML",
        )
        context.user_data["otp_instruction_msg_id"] = msg.message_id # 👈 Track it
        return


async def handle_wallet_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    step = context.user_data.get("wallet_step")
    if not step:
        return False

    text = (update.message.text or "").strip()
    
        # ✅ if user types a command, don't treat it as amount
    if text.startswith("/"):
        return False
    
    if text.lower() in ("cancel", "back"):    
        context.user_data.pop("wallet_step", None)
        await safe_send(update, context, "✅ Cancelled. Use menu buttons.")
        return True


    if step == "await_amount":
        try:
            amt = Decimal(text)
        except (InvalidOperation, ValueError):
            await safe_send(update, context,"❌ Invalid amount. Example: 10")
            return True

        if amt <= 0:
            await safe_send(update, context, "❌ Amount must be greater than 0.")
            return True

        user_id = update.effective_user.id

        # Expire old pending so we don’t block user forever
        expire_pending_order_if_needed(user_id)

        # If pending wallet_topup exists, do NOT create a new one. Show existing.
        pending = get_pending_order(user_id)
        handled = await _show_existing_topup_or_continue(update, context, pending)
        if handled:
            context.user_data.pop("wallet_step", None)
            return True

        # Create top-up order
        desc = f"WALLET_TOPUP:{float(amt):.2f}"
        _, order_code = create_order(
            user_id,
            desc,
            ttl_seconds=3600,
            amount_usd=float(amt),
            order_type="wallet_topup",
        )

        context.user_data.pop("wallet_step", None)

        # Send to existing payment UI (coin selection happens there)
        await show_make_payment(update, context, order_code)
        return True

    return False
