import os
import asyncio
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton,ReplyKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from payments.plisio import create_plisio_invoice
from utils.db import get_pending_order, set_order_payment,expire_pending_order_if_needed,update_order_status,update_payment_status_by_order_code,create_order
from pricelist import get_price, COIN_MAP, get_plisio_min_usd
import datetime
from handlers.wallet_continue import open_wallet_menu
from handlers.menu_commands import handle_main_menu
from utils.auto_delete import delete_tracked_message

from utils.helper import notify_admin



logger = logging.getLogger(__name__)


def make_payment_kb(order_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Make Payment", callback_data=f"pay_make:{order_code}")]
    ])
    

def coin_picker_kb(order_code: str, amount_usd: float) -> InlineKeyboardMarkup:
    """
    Standard Crypto Picker with 2 columns.
    USDT leads to the network selection menu.
    """
    def label_for(plisio_code: str, text: str) -> str:
        min_req = get_plisio_min_usd(plisio_code)
        # ✅ Updated to use "minimum" as requested
        return f"{text} (minimum ${min_req:g})" if amount_usd < min_req else text

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
    """
    Specific USDT Network selector (TRC20 vs ERC20).
    """
    trc_min = get_plisio_min_usd("USDT_TRX")
    erc_min = get_plisio_min_usd("USDT_ETH")

    trc_label = "USDT (TRC20)"
    erc_label = "USDT (ERC20)"
    
    # ✅ Updated to use "minimum" as requested
    if amount_usd < trc_min:
        trc_label += f" (minimum ${trc_min:g})"
    if amount_usd < erc_min:
        erc_label += f" (minimum ${erc_min:g})"

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
        [
            InlineKeyboardButton("🔗 Open payment", url=str(invoice_url)),
            InlineKeyboardButton("🗑 Cancel & new", callback_data=f"pay_cancel:{order_code}"),
        ]
    ])



async def safe_edit_message(q, context, text: str, reply_markup=None, **kwargs):
    """
    Edit the callback message safely, and keep auto-delete tracking consistent
    with safe_send() by updating last_bot_message_id.
    """
    try:
        await q.edit_message_text(text, reply_markup=reply_markup, **kwargs)

        # Track the edited message as the "last bot message"
        context.user_data["last_bot_message_id"] = q.message.message_id
        context.user_data["last_bot_message_had_reply_kb"] = isinstance(reply_markup, ReplyKeyboardMarkup)

    except BadRequest as e:
        msg = str(e).lower()

        if "message is not modified" in msg:
            # Still track it, so the system doesn't drift
            context.user_data["last_bot_message_id"] = q.message.message_id
            context.user_data["last_bot_message_had_reply_kb"] = isinstance(reply_markup, ReplyKeyboardMarkup)
            return

        if "message can't be edited" in msg:
            sent = await q.message.reply_text(text, reply_markup=reply_markup, **kwargs)

            # Track the newly sent message
            context.user_data["last_bot_message_id"] = sent.message_id
            context.user_data["last_bot_message_had_reply_kb"] = isinstance(reply_markup, ReplyKeyboardMarkup)
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
    
    # --- 👻 THE GHOST ORDER INTERCEPTOR ---
    if ":PENDING" in data:
        amt = context.user_data.get("pending_wallet_amount")
        if not amt:
            await q.edit_message_text("❌ Session expired. Please restart.")
            return

        # If they finally click a crypto coin, WE CREATE THE REAL ORDER NOW!
        if data.startswith("pay_coin:"):
            user_id = q.from_user.id
            expire_pending_order_if_needed(user_id)
            desc = f"WALLET_TOPUP:{float(amt):.2f}"
            
            # ✅ Write to database!
            _, real_order_code = create_order(
                user_id, desc, ttl_seconds=3600, amount_usd=float(amt), order_type="wallet_topup"
            )
            # Swap PENDING with the real code so the rest of the function works
            data = data.replace("PENDING", real_order_code)
            pending = get_pending_order(user_id)
            chk = None
            
        else:
            # They just clicked "Make Payment", "USDT", or "Back". Keep it a Ghost!
            pending = {
                "order_code": "PENDING", 
                "amount_usd": amt, 
                "order_type": "wallet_topup",
                "invoice_url": "",
                "pay_status": ""
            }
            chk = None

    # --- NORMAL FLOW (Existing DB Orders like eSIM or Rentals) ---
    else:
        pending = get_pending_order(q.from_user.id)
        if not pending:
            await q.edit_message_text("❌ No pending order.")
            return
       
        chk = expire_pending_order_if_needed(q.from_user.id)
        if chk and chk.get("status") == "expired":
            await q.edit_message_text("Your previous order expired. Please create a new order.")
            return

    # --- NORMAL ROUTING CONTINUES BELOW ---
    order_code = pending["order_code"]
    desc = (pending.get("description") or "").strip() or "Service"
    order_type = (pending.get("order_type") or "").lower().strip()

    # Determine amount
    if order_type == "wallet_topup":
        amount_usd = _safe_float(pending.get("amount_usd"))
    else:
        amount_usd = _resolve_amount_usd(context, pending)

    if amount_usd is None:
        await safe_edit_message(q, context,
            "❌ Could not determine price for this order.\nPlease restart the order and try again."
        )
        return
    
    existing_url = (pending.get("invoice_url") or "").strip()
    existing_status = (pending.get("pay_status") or "").lower().strip()
        
    expires_at = pending.get("expires_at")
    remaining = None
    if expires_at:
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            
        if expires_at.tzinfo is None:
            expires_at = expires_at.astimezone(datetime.timezone.utc).replace(tzinfo=None)
            
        now = datetime.datetime.utcnow()
        remaining = int((expires_at - now).total_seconds())    
        if remaining < 0:
            remaining = 0

    # If invoice already exists and still usable, reuse it
    if not data.startswith("pay_cancel:"):
        if existing_url and existing_status in {"pending", "processing", "detected"}:
            if order_type == "wallet_topup" and remaining and remaining > 0:
                await safe_edit_message(q, context,
                    f"✅ You already have an active top up.\n"
                    f"⏳ Time left: {remaining//60} min\n\n"
                    f"Tap below to continue or cancel and create a new top up.",
                    reply_markup=open_invoice_cancel_kb(existing_url, order_code),   
                )
                
                # ✅ 1. Remove it from the Interceptor's radar
                context.user_data.pop("otp_instruction_msg_id", None)

                # ✅ 2. Create the mini self-destruct function
                async def _auto_delete_warning(ctx: ContextTypes.DEFAULT_TYPE):
                    try:
                        await ctx.bot.delete_message(
                            chat_id=ctx.job.data["chat_id"], 
                            message_id=ctx.job.data["msg_id"]
                        )
                    except Exception:
                        pass

                # ✅ 3. Start the 120-second timer
                if context.job_queue and q.message:
                    context.job_queue.run_once(
                        _auto_delete_warning, 
                        when=60, 
                        data={"chat_id": update.effective_chat.id, "msg_id": q.message.message_id}
                    )
                return
            
            # fallback for non-topup orders
            await safe_edit_message(q, context,
                f"✅ Payment link already created for this order.\n Tap below to open payment page:",
                reply_markup=open_invoice_kb(existing_url),
            )
            return

    # ---- ROUTING: handle the pressed button ----
    if data.startswith("pay_back:"):
        # ✅ If they back out of the Ghost Order, return to Wallet Menu entirely
        if data == "pay_back:PENDING":
            context.user_data.pop("pending_wallet_amount", None)
            await open_wallet_menu(update, context)
            return
            
        await q.edit_message_text("Tap below to pay:", reply_markup=make_payment_kb(order_code))
        return

    if data.startswith("pay_make:"):
        kb = coin_picker_kb(order_code, amount_usd)
        logger.info("pay_make keyboard=%r", kb.to_dict())
        await safe_edit_message(q, context,
            f"Minimum Deposit <b>$4</b>\n"
            f"Coins Like Usdt Trc Miniumums are $5.50, Usdt Erc $11\n\n"             
            f"<b>Choose a Payment Currency:\n\n</b>"
            f"Amount You Entered Is: <b> ${amount_usd:.2f}</b>",
            reply_markup=coin_picker_kb(order_code, amount_usd),
            parse_mode="HTML",
        )
        return

    if data.startswith("pay_usdt:"):
        await safe_edit_message(q, context,
            "Choose USDT network:",
            reply_markup=usdt_network_kb(order_code, amount_usd),
        )
        return
    
    if data.startswith("pay_cancel:"):
        # 1. Update DB only if it's a real record
        if order_code != "PENDING" and pending:
            update_order_status(pending["id"], "cancelled")
            update_payment_status_by_order_code(order_code, pay_status="cancelled", pay_txn_id=None)
        
        # 2. Get the menu they were on BEFORE clearing memory
        last_menu = context.user_data.get("current_menu")

        # 🧹 3. Vaporize ALL flow memory
        keys_to_clear = [
            "wallet_step", "otp_step", "msn_step", "esim_step", 
            "esim_email", "esim_duration", "esim_country", "custom_price_usd",
            "order_pending_description", "pending_wallet_amount"
        ]
        for k in keys_to_clear:
            context.user_data.pop(k, None)

        # 4. Clear the "Pending Order" prompt if it exists
        await delete_tracked_message(context, update.effective_chat.id, "pending_prompt_msg_id")

        # 🚀 5. SMART REDIRECT
        if last_menu == "wallet":
            from handlers.wallet_continue import open_wallet_menu
            await open_wallet_menu(update, context)
        else:
            # Go to Main Menu (Tools/Orders)
          
            await handle_main_menu(update, context)
            
        return
    
    if data.startswith("pay_coin:"):
        # Expected: pay_coin:<order_code>:<coin_key>
        try:
            _, _, coin_key = data.split(":")
        except ValueError:
            await safe_edit_message(q, context,"❌ Invalid selection. Try again.")
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
            
            # Safety check: Update payment only if order exists in DB
            if pending and "id" in pending:
                set_order_payment(
                    pending["id"],
                    invoice_url=invoice_url,
                    pay_currency=plisio_currency,
                    pay_provider="plisio",
                    pay_status="pending",
                )
            
            # Safely calculate remaining time for display (Fallback to 59 if brand new)
            display_rem = remaining // 60 if remaining else 59

            sent_msg = await q.edit_message_text(
                f"✅ <b>Payment link created</b>\n\n"
                f"<b>Order:</b> <code>{order_code}</code>\n"
                f"<b>Amount:</b> ${amount_usd:.2f}\n"
                f"<b>Currency:</b> {plisio_currency}\n\n"
                f"⏳ <b>Time left:</b> {display_rem} min\n\n"
                f"Tap below to open payment page:",
                reply_markup=open_invoice_kb(invoice_url),
                parse_mode="HTML"
            )
            
            context.user_data.pop("otp_instruction_msg_id", None)
            
            # ✅ Start the 2-minute timer
            async def _delete_after_delay(chat_id, msg_id, delay=120):
                await asyncio.sleep(delay)
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
                except Exception:
                    pass 
                
                
            asyncio.create_task(_delete_after_delay(q.message.chat_id, sent_msg.message_id))
            return

        except Exception as e:
            # 1. Log the real error to your server console
            logger.exception("Payment invoice creation failed: %s", str(e))
            await notify_admin(f"Payment invoice creation failed: {e}")
            msg = str(e).lower()

            # 2. Check for the duplicate invoice edge-case
            if "already exists" in msg or "return_existing" in msg:
                await safe_edit_message(q, context,
                    "⚠️ Payment link already exists for this order.\nTap below to continue:",
                    reply_markup=make_payment_kb(order_code),
                )
                return

            # 3. 🚨 Send a completely safe, white-labeled error to the user
            await q.edit_message_text(
                "❌ The payment network is currently unresponsive. Please wait a moment and try again, or choose another coin.",
                reply_markup=coin_picker_kb(order_code, amount_usd),
            )
            return

    # Unknown callback
    await q.edit_message_text("❌ Unknown action. Please try again.")