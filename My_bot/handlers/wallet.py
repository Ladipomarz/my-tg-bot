from decimal import Decimal, InvalidOperation

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
        elif status in ("detected", "processing"):
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
        "➕ To top up: press <b>Top up</b>, then enter an amount (example: <b>10</b>)."
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

    if q.data == "back_main":
        await q.message.reply_text("⬅ Back. Use the main menu buttons below.")
        return

    if q.data == "wallet_topup":
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

        pending = get_pending_order(user_id)
        if pending:
            # ✅ Don’t block — just show the existing pending order payment button
            # Also set amount for payments.py resolver
            pending_amt = pending.get("amount_usd")
            if pending_amt:
                context.user_data["custom_price_usd"] = float(pending_amt)

            context.user_data.pop("wallet_step", None)
            await show_make_payment(update, context, pending["order_code"])
            return True

        # ✅ Create top-up order (capture return!)
        desc = f"WALLET_TOPUP:{amt:g}"
        order_id, order_code = create_order(
            user_id,
            desc,
            ttl_seconds=3600,
            amount_usd=float(amt),
            order_type="wallet_topup",
        )

        # ✅ payments.py uses this to decide amount
        context.user_data[pending.amount_usd] = float(amt)

        context.user_data.pop("wallet_step", None)

        # ✅ Reuse your existing payment UI (this creates callback_data pay_make:<order_code>)
        await show_make_payment(update, context, order_code)


        return True

    return False
