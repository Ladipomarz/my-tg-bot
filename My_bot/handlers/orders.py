import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from menus.orders_menu import (
    get_orders_menu,
    get_pending_order_menu,
    get_order_confirm_menu,
)
from menus.tools_menu import get_tools_inline
from utils.auto_delete import safe_send

from utils.db import (
    create_order,
    get_pending_order,
    expire_pending_order_if_needed,
    update_order_status,
    get_orders_for_user,
)


def _pending_text(order: dict) -> str:
    now = datetime.datetime.utcnow()
    expires_at = order.get("expires_at")

    lines = [f"🕒 Pending order {order['order_code']}"]

    if expires_at:
        remaining = int((expires_at - now).total_seconds())
        if remaining <= 0:
            lines.append("⌛ Status: Expired")
        else:
            minutes = remaining // 60
            lines.append(f"⏳ Expires in: {minutes} min")

    lines.append("What do you want to do?")
    return "\n".join(lines)


def open_invoice_kb(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Open payment page", url=url)]])


# ---------- GLOBAL CONFIRM HELPER ----------

async def ask_order_confirmation(
    update_or_query,
    context: ContextTypes.DEFAULT_TYPE,
    display_text: str,
    order_description: str,
):
    context.user_data["order_pending_description"] = order_description

    await safe_send(
        update_or_query,
        context,
        f"{display_text}\n\nCreate an order for: {order_description}?",
        reply_markup=get_order_confirm_menu(),
    )


# ---------- ORDERS MENU ----------

async def open_orders_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_send(update, context, "Orders:", reply_markup=get_orders_menu())


# ---------- ORDERS CALLBACK ----------

async def orders_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    # 🆕 New Order
    if data == "orders_new":
        pending = expire_pending_order_if_needed(user_id)

        if pending and pending.get("status") == "pending":
            context.user_data["orders_order_id"] = pending["id"]
            context.user_data["orders_order_code"] = pending["order_code"]

            await safe_send(
                query,
                context,
                _pending_text(pending),
                reply_markup=get_pending_order_menu(),
            )
            return

        await safe_send(query, context, "Tools:", reply_markup=get_tools_inline())
        return

    # 📂 Order History
    if data == "orders_history":
        orders = get_orders_for_user(user_id)

        if not orders:
            await safe_send(query, context, "You have no orders yet.")
            return

        lines = ["Your last orders:"]
        for o in orders:
            emoji = {
                "pending": "🕒",
                "paid": "💰",
                "completed": "✅",
                "cancelled": "❌",
                "expired": "⌛",
            }.get(o["status"], "❔")

            lines.append(f"{emoji} {o['order_code']} — {o['status']}")

        await safe_send(query, context, "\n".join(lines))
        return

    # ✅ Continue pending
    if data == "orders_continue":
        pending = expire_pending_order_if_needed(user_id)

        if not pending or pending.get("status") != "pending":
            await safe_send(query, context, "No active pending order.")
            return

        invoice_url = pending.get("invoice_url")

        if invoice_url:
            await safe_send(
                query,
                context,
                _pending_text(pending),
                reply_markup=open_invoice_kb(invoice_url),
            )
            return

        await safe_send(query, context, "Tools:", reply_markup=get_tools_inline())
        return

    # ❌ Cancel pending
    if data == "orders_cancel_pending":
        pending = get_pending_order(user_id)
        if not pending:
            await safe_send(query, context, "No pending order found.")
            return

        update_order_status(pending["id"], "cancelled")
        await safe_send(query, context, f"❌ Order {pending['order_code']} cancelled.")
        return

    # ✅ Proceed
    if data == "orders_proceed":
        desc = context.user_data.get("order_pending_description", "SSN Service")

        order_id, order_code = create_order(
            user_id=user_id,
            description=desc,
            ttl_seconds=3600,  # 1 hour
        )

        context.user_data["orders_order_id"] = order_id
        context.user_data["orders_order_code"] = order_code

        from handlers.payments import show_make_payment
        await show_make_payment(update, context, order_code)

        context.user_data.pop("order_pending_description", None)
        return

    # ❌ Cancel create
    if data == "orders_cancel":
        context.user_data.pop("order_pending_description", None)
        await safe_send(query, context, "Order not created.")
        return

    # ⬅ Back
    if data == "orders_back":
        await safe_send(query, context, "Orders:", reply_markup=get_orders_menu())
        return

