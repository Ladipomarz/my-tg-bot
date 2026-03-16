from telegram import Update
from telegram.ext import ContextTypes
import asyncio
from utils.db import add_user, expire_pending_order_if_needed
from menus.main_menu import get_main_menu
from menus.orders_menu import get_pending_order_menu
from handlers.tools import open_tools_menu
from handlers.orders import open_orders_menu
from config import ADMIN_IDS
from config import SUPPORT_HANDLE
from handlers.wallet_continue import open_wallet_menu
from utils.auto_delete import safe_send
from handlers.global_flow import handle_global_start

from handlers.otp_handler import otp_verification_handler,show_usa_verification_menu,show_other_countries_menu


def _norm_menu_text(t: str) -> str:
    t = (t or "").strip().lower()
    for ch in ["🧰", "🛒", "👤", "💰" ,"🛠", "🇺🇸", "🌍"]: 
        t = t.replace(ch, "")
    t = " ".join(t.split())
    return t


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # 1. Database & State Cleanup
    add_user(
        user_id=user.id,
        first_name=user.first_name,
        username=user.username,
    )

    # ✅ CLEAR ANY ACTIVE "CAPTURE" FLOWS
    for k in ("wallet_step", "otp_step", "msn_step", "esim_step"):
        context.user_data.pop(k, None)

    admin_badge = " (Admin)" if user.id in ADMIN_IDS else ""

    # 2. Send the Welcome Message
    # We use safe_send and capture the 'msg' object so we have the ID
    msg = await safe_send(
        update_or_query=update,
        context=context,
        text=f"Hello User 😊<b>{user.id}{admin_badge}</b> Welcome 👋 to your Number One underground bot, where full PRIVACY is Our Top Suit.",
        reply_markup=get_main_menu(),
        parse_mode="HTML"
    )

    # 3. schedule the 10-Minute Self-Destruct (600 seconds)
    if msg:
        # Fire and forget: This runs in the background
        asyncio.create_task(vaporize_after_delay(context, msg.chat_id, msg.message_id, 600))


# --- Add this helper function at the bottom of menu_commands.py ---
async def vaporize_after_delay(context, chat_id, message_id, delay):
    """Wait for 'delay' seconds and then delete the message"""
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        # Message might already be deleted by the Janitor or User
        pass


async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Identify where the interaction came from (Message or Button)
    query = update.callback_query
    
    if query:
        # It's a button click (callback)
        raw_text = "" 
        msg = query.message
    else:
        # It's a typed message or keypad tap
        raw_text = update.message.text or ""
        msg = update.message

    # 2. Key normalization
    key = _norm_menu_text(raw_text)
    print(f"user tapped: {repr(raw_text)} -> {repr(key)}")

    # 3. Flow Check
    if context.user_data.get("msn_step"):
        return
        
    # ✅ Keypad: Purchase USA Number
    if key == "purchase usa number":
        # Capture the message so we can track it!
        msg = await show_usa_verification_menu(
            update, 
            context, 
            message_text="Please choose the verification method:"
        )
        if msg:
            context.user_data["otp_instruction_msg_id"] = msg.message_id
        return

    # ✅ Keypad: Purchase Non Number (Unified)
    if key == "purchase non number":
        # We call the handler directly so it runs the ADMIN_IDS check 
        # and decides whether to show 'Coming Soon' or the 'Admin Menu'
        await handle_global_start(update, context)
        return
    
    if key == "tools":
        pending = expire_pending_order_if_needed(update.effective_user.id)

        #if pending:
            #print(f"GATE CHECK: {pending.get('order_code')} status={pending.get('status')} pay_status={pending.get('pay_status')}")
        #else:
           # print("GATE CHECK: no pending order")

        if pending and pending.get("status") == "pending":
            pay_status = (pending.get("pay_status") or "").lower().strip()

            # 🚫 Block ONLY if payment NOT detected yet
            if pay_status in {"pending", "", "new"}:
                from utils.auto_delete import safe_send
                from menus.orders_menu import get_pending_order_menu
                await safe_send(
                    update,
                    context,
                    f"🕒 You have a pending order <code>{pending['order_code']}</code>.\nWhat do you want to do?",
                    reply_markup=get_pending_order_menu(),
                )
                return

        return await open_tools_menu(update, context)

    # ✅ Orders
    if key == "orders":
        return await open_orders_menu(update, context)
    
    # ✅ Credit (Wallet)
    if key == "credit":
        return await open_wallet_menu(update, context)    
    
    
    # ✅ Support Keypad (Redirecting to your existing help_cmd)
    if key == "support":
        from handlers.menu_commands import help_cmd
        return await help_cmd(update, context)