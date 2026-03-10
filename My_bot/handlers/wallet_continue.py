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

    # 1. Cleanup before starting
    expire_pending_order_if_needed(user_id)

    # 2. Fetch Data
    bal = get_user_balance_usd(user_id)
    txs = get_last_wallet_transactions(user_id, limit=5)

    # 3. Build the Transaction list
    lines = []
    for t in txs:
        amt = t.get("amount_usd")
        status = (t.get("status") or t.get("pay_status") or "unknown").lower()
        
        # Format the date nicely
        date_obj = t.get("created_at")
        date_str = ""
        if date_obj:
            try:
                date_str = date_obj.strftime("%b %d") + " - "
            except Exception:
                pass 
        
        # Determine status text
        if status in ("paid", "confirmed", "completed", "detected"):
            status_txt = "Completed"
        elif status in ("expired",):
            status_txt = "Expired"
        elif status in ("cancelled", "canceled", "cancel"):
            status_txt = "Canceled"
        elif status in ("processing", "pending"):
            status_txt = "Pending"
        else:
            status_txt = status.capitalize()

        lines.append(f"• {date_str}{_fmt_usd(amt or 0)} Top-up ({status_txt})")

    tx_block = "\n".join(lines) if lines else "- No transactions yet."

    # 4. Construct Full Message Text
    wallet_text = (
        f"<b>💰 Wallet</b>\n\n"
        f"<b>Balance:</b> {_fmt_usd(bal)}\n\n"
        f"<b>Last 5 transactions:</b>\n{tx_block}\n\n"
        "➕ To top up: press <b>Top up</b>."
    )

    # 5. Define the Keyboard
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Top up", callback_data="wallet_topup"),
            InlineKeyboardButton("Close", callback_data="back_main"),
        ],
    ])

    # 6. SEND ONCE using safe_send
    # safe_send automatically handles edits vs new messages!
    msg = await safe_send(
        update,
        context,
        wallet_text,
        reply_markup=keyboard,
        parse_mode="HTML"
    )

    # 7. TRACK THE ID for global menu cleanup (bot.py text_router)
    context.user_data["otp_instruction_msg_id"] = msg.message_id
