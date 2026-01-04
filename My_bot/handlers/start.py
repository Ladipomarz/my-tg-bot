from telegram import Update
from telegram.ext import ContextTypes

from utils.db import add_user, expire_pending_order_if_needed
from menus.main_menu import get_main_menu
from menus.orders_menu import get_pending_order_menu

from handlers.tools import open_tools_menu
from handlers.orders import open_orders_menu
from config import ADMIN_IDS


def _norm_menu_text(t: str) -> str:
    t = (t or "").strip().lower()
    for ch in ["🧰", "🛒", "👤", "💵"]:
        t = t.replace(ch, "")
    t = " ".join(t.split())
    return t


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    add_user(
        user_id=user.id,
        first_name=user.first_name,
        username=user.username,
    )

    admin_badge = " (Admin)" if user.id in ADMIN_IDS else ""

    await update.message.reply_text(
        f"Hello {user.first_name}{admin_badge}! Welcome to your underground bot.",
        reply_markup=get_main_menu(),
    )


async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text or ""
    key = _norm_menu_text(raw_text)

    print("user tapped:", repr(raw_text), "->", repr(key))

    if context.user_data.get("msn_step"):
        return

    # ✅ Tools (ReplyKeyboard)
    if key == "tools":
        pending = expire_pending_order_if_needed(update.effective_user.id)

        # ✅ DEBUG (shows what gate sees)
        if pending:
            print(
                "GATE CHECK:",
                pending.get("order_code"),
                "status=",
                pending.get("status"),
                "pay_status=",
                pending.get("pay_status"),
            )
        else:
            print("GATE CHECK: no pending order")

        if pending and pending.get("status") == "pending":
            pay_status = (pending.get("pay_status") or "").lower().strip()

            # 🚫 Block ONLY if payment NOT detected yet
            if pay_status in {"pending", "", "new"}:
                await update.message.reply_text(
                    f"🕒 You have a pending order {pending['order_code']}.\nWhat do you want to do?",
                    reply_markup=get_pending_order_menu(),
                )
                return

        # ✅ If pay_status is "detected" or "paid" -> allow tools normally
        return await open_tools_menu(update, context)

    # ✅ Orders (ReplyKeyboard)
    if key == "orders":
        return await open_orders_menu(update, context)

    await update.message.reply_text("Unknown command, please use menu buttons.")
