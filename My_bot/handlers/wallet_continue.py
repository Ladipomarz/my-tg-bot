from decimal import Decimal
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from utils.auto_delete import safe_send
from utils.db import get_user_balance_usd, get_last_wallet_transactions, expire_pending_order_if_needed


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
        status = (t.get("status") or t.get("pay_status") or "unknown").lower()
        
        if status in ("paid", "confirmed", "completed"):
            status_txt = "Completed"
        elif status in ("expired",):
            status_txt = "Expired"
        elif status in ("cancelled", "canceled", "cancel"):
            status_txt = "Canceled"
        elif status in ("detected",):
            status_txt = "Completed"
        elif status in ("processing", "pending"):
            status_txt = "Pending"

        else:
            status_txt = status.capitalize()

        lines.append(f"- {_fmt_usd(amt or 0)} Top-up ({status_txt})")

    tx_block = "\n".join(lines) if lines else "- No transactions yet."

    msg = (
        f"<b>💰 Wallet</b>\n\n"
        f"<b>Balance:</b> {_fmt_usd(bal)}\n\n"
        f"<b>Last 5 transactions:</b>\n{tx_block}\n\n"
        "➕ To top up: press <b>Top up</b>."
    )

    keyboard = [
    [
        InlineKeyboardButton("➕ Top up", callback_data="wallet_topup"),
        InlineKeyboardButton("⬅ Back", callback_data="back_main"),
    ],
]


    if update.message:
        await safe_send(update, context, msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        q = update.callback_query
        try:
            await q.edit_message_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        except BadRequest as e:
            em = str(e).lower()
            if "message is not modified" in em:
                return
            if "message can't be edited" in em:
                await q.message.reply_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
                return
            raise
