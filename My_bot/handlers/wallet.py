from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from handlers.payments import show_make_payment
from utils.db import (
    get_user_balance_usd,
    get_last_wallet_transactions,
    create_order,
    expire_pending_order_if_needed,
    get_pending_order,
)

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

async def open_wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id

    # Expire old pending orders so wallet doesn’t get stuck
    expire_pending_order_if_needed(user_id)

    bal = get_user_balance_usd(user_id)
    txs = get_last_wallet_transactions(user_id, limit=5)

    lines = []
    for t in txs:
        amt = t.get("amount_usd")
        status = (t.get("pay_status") or t.get("status") or "unknown").lower()
        if status in ("paid", "confirmed", "completed"):
            status = "Completed"
        elif status in ("detected", "processing", "pending"):
            status = "Pending"
        elif status in ("expired", "cancelled", "canceled"):
            status = "Canceled"
        else:
            status = status.capitalize()

        lines.append(f"- {_fmt_usd(amt or 0)} Top-up ({status})")

    tx_block = "\n".join(lines) if lines else "- No transactions yet."

    msg = (
        f"<b>💰 Wallet</b>\n\n"
        f"<b>Balance:</b> {_fmt_usd(bal)}\n\n"
        f"<b>Last 5 transactions:</b>\n{tx_block}\n\n"
        "➕ To top up: press <b>Top up</b>."
    )

    keyboard = [
        [InlineKeyboardButton("➕ Top up", callback_data="wallet_topup")],
        [InlineKeyboardButton("⬅ Back", callback_data="back_main")],
    ]

    if update.message:
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.edit_message_text(
            msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard)
        )

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

        # 2) If there is an active wallet_topup pending, DO NOT ask for amount.
        pending = get_pending_order(user_id)
        if pending and (pending.get("order_type") or "").lower() == "wallet_topup":
            secs_left = _seconds_left_from_expires_at(pending.get("expires_at"))
            # If somehow expired_at is missing, treat as no time left
            if secs_left > 0:
                # Send them back to the payment flow for the same order
                await q.message.reply_text(
                    "✅ You already have an active top up.\n"
                    f"⏳ Time left: {_fmt_left(secs_left)}\n\n"
                    "Continuing your existing top up…",
                    parse_mode="HTML",
                )
                context.user_data.pop("wallet_step", None)
                await show_make_payment(update, context, pending["order_code"])
                return

        # 3) Otherwise ask for amount
        context.user_data["wallet_step"] = "await_amount"
        await q.message.reply_text(
            "💳 <b>Top up Wallet</b>\n\nEnter the amount in USD (example: <b>10</b>).",
            parse_mode="HTML",
        )
        return

async def handle_wallet_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    step = context.user_data.get("wallet_step")
    if not step:
        return False

    text = (update.message.text or "").strip()

    if step == "await_amount":
        try:
            amt = Decimal(text)
        except (InvalidOperation, ValueError):
            await update.message.reply_text("❌ Invalid amount. Example: 10")
            return True

        if amt <= 0:
            await update.message.reply_text("❌ Amount must be greater than 0.")
            return True

        user_id = update.effective_user.id

        # Expire old pending so we don’t block user forever
        expire_pending_order_if_needed(user_id)

        # If pending wallet_topup exists, do NOT create a new one.
        pending = get_pending_order(user_id)
        if pending and (pending.get("order_type") or "").lower() == "wallet_topup":
            secs_left = _seconds_left_from_expires_at(pending.get("expires_at"))
            if secs_left > 0:
                await update.message.reply_text(
                    "✅ You already have an active top up.\n"
                    f"⏳ Time left: {_fmt_left(secs_left)}\n\n"
                    "Continuing your existing top up…",
                    parse_mode="HTML",
                )
                context.user_data.pop("wallet_step", None)
                await show_make_payment(update, context, pending["order_code"])
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

        # Send to existing payment UI
        await show_make_payment(update, context, order_code)
        return True

    return False
