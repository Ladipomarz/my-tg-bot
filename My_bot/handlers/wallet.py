from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from utils.auto_delete import safe_send
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from decimal import Decimal, InvalidOperation
from handlers.payments import show_make_payment, open_invoice_cancel_kb, make_payment_kb
from utils.auto_delete import safe_send, safe_delete_user_message
from utils.db import (
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


import asyncio # 👈 Make sure this is at the very top of your file!

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

    msg_target = update.callback_query.message if update.callback_query else update.message
    if not msg_target:
        return False

    # ✅ 1. Create the bulletproof asyncio self-destruct function
    async def _delete_after_delay(chat_id, msg_id, delay=120):
        await asyncio.sleep(delay) # Pauses in the background for 120 seconds
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass # Fails silently if user already clicked 'Cancel and new'

    if invoice_url:
        # ✅ 2. Send the correctly formatted HTML message
        sent_msg = await msg_target.reply_text(
            "✅ <b>You already have an active top up. ❗</b>\n\n"
            f"<b>Order:</b> {order_code} \n\n"
            f"<b>Amount In Usd:</b> ${float(amount):.2f}\n"
            f"<b>Currency:</b> {currency}\n\n"
            f"⏳ <b>Time left:</b> {_fmt_left(secs_left)}\n\n"
            "Tap below to continue or cancel and create a new top up.",
            reply_markup=open_invoice_cancel_kb(invoice_url, order_code),
            parse_mode="HTML", # 👈 Renders the bold and code blocks
        )
        
        # ✅ 3. Start the 120-second background timer
        asyncio.create_task(_delete_after_delay(update.effective_chat.id, sent_msg.message_id))
        return True

    # No invoice yet -> send them to payment menu (coin selection happens in payments.py)
    sent_msg = await msg_target.reply_text(
        "✅ <b>You already started a top up.</b>\n\n"
        f"⏳ <b>Time left:</b> {_fmt_left(secs_left)}\n\n"
        "Continue to payment:",
        reply_markup=make_payment_kb(order_code),
        parse_mode="HTML",
    )
    
    # ✅ Start the 120-second background timer for this one too
    asyncio.create_task(_delete_after_delay(update.effective_chat.id, sent_msg.message_id))
    return True

async def wallet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    q = update.callback_query
    await q.answer()

    user_id = update.effective_user.id

    if q.data == "back_main":
        # ❌ The user clicked "Close" on the top-level menu
        # Just quietly delete the inline menu to clean the screen!
        try:
            await q.message.delete()
        except Exception:
            pass
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
            f"💳<b>Top up Wallet</b>\n\n"
            f"General Minimum Deposit Is <b>$4</b> *BUT PLEASE NOTE THAT* \n\n"
            f"Coins Like Usdt Trc 20 Requires a Minimum Of<b> $5.50</b>\n"
            f"Coins Like Usdt Erc 20 Requires a Minimum Of <b> $11.00</b>\n\n\n" 
            f"Enter the Amount in USD (Example: <b>4</b> for <b>$ 4</b>).",
            parse_mode="HTML",
        )
        context.user_data["otp_instruction_msg_id"] = msg.message_id # 👈 Track it
        return


async def handle_wallet_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    from utils.auto_delete import safe_send
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
        asyncio.create_task(safe_delete_user_message(update))
        clean_text = text.replace("$", "").strip()
        try:
            amt = Decimal(clean_text)
        except (InvalidOperation, ValueError):
            msg = await safe_send(update, context,"! Invalid Input, Example: 4,Kindly Enter a valid amount ")
            
            if msg:
                context.user_data["otp_instruction_msg_id"] = msg.message_id
            return True
            
        if amt < 4:
            msg = await safe_send(update, context, "! Minimum deposit is $4, Please Input Amount.")
            if msg:
                context.user_data["otp_instruction_msg_id"] = msg.message_id
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

        # 👻 1. GHOST ORDER: Save amount to memory, DO NOT create DB order!
        context.user_data["pending_wallet_amount"] = float(amt)
        context.user_data.pop("wallet_step", None)

        # 👻 2. Send the "Make Payment" button using the fake PENDING code
        from handlers.payments import show_make_payment
        await show_make_payment(update, context, "PENDING")
        return True

    return False
