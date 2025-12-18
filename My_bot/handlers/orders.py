from telegram import Update
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
    update_order_status,
    get_orders_for_user,
)


# ---------- GLOBAL CONFIRM HELPER ----------

async def ask_order_confirmation(
    update_or_query,
    context: ContextTypes.DEFAULT_TYPE,
    display_text: str,
    order_description: str,
):
    """
    Global function any tool can call at the END of its flow.

    - display_text: what the user sees in the bubble (e.g. "SSN submitted! ...")
    - order_description: short name to store in DB (e.g. "SSN Services")

    Shows display_text + Proceed/Cancel keyboard.
    On Proceed -> we create an order in this file.
    """
    context.user_data["order_pending_description"] = order_description

    text = f"{display_text}\n\nCreate an order for: {order_description}?"
    await safe_send(
        update_or_query,
        context,
        text,
        reply_markup=get_order_confirm_menu(),
    )


# ---------- Open orders main menu ----------

async def open_orders_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_send(
        update,
        context,
        "Orders:",
        reply_markup=get_orders_menu(),
    )


# ---------- Inline button handler for orders ----------

async def orders_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    # 🆕 New Order
    if data == "orders_new":
        pending = get_pending_order(user_id)

        if pending:
            order_id, _user_id, order_code, status, desc, created_at = pending
            context.user_data["orders_order_id"] = order_id
            context.user_data["orders_order_code"] = order_code

            text = (
                f"You have a pending order {order_code}.\n"
                "What do you want to do?"
            )
            await safe_send(
                query,
                context,
                text,
                reply_markup=get_pending_order_menu(),
            )
            return

        await safe_send(
            query,
            context,
            "Tools:",
            reply_markup=get_tools_inline(),
        )
        return

    # 📂 Order History
    elif data == "orders_history":
        orders = get_orders_for_user(user_id)

        if not orders:
            await safe_send(query, context, "You have no orders yet.")
            return

        lines = ["Your last orders:"]
        for (oid, uid, code, status, desc, created_at) in orders:
            status_emoji = {
                "pending": "🕒",
                "completed": "✅",
                "cancelled": "❌",
            }.get(status, "❔")

            if not desc:
                desc = "No name set"

            lines.append(f"{status_emoji} {code} [{status}] — {desc}")

        await safe_send(query, context, "\n".join(lines))
        return

    # ✅ Continue pending order
    elif data == "orders_continue":
        pending = get_pending_order(user_id)
        if not pending:
            await safe_send(query, context, "No pending order found.")
            return

        order_id, _uid, order_code, status, desc, created_at = pending
        context.user_data["orders_order_id"] = order_id
        context.user_data["orders_order_code"] = order_code

        await safe_send(
            query,
            context,
            f"Continuing pending order {order_code}\nOpening Tools menu...",
        )

        await safe_send(
            query,
            context,
            "Tools:",
            reply_markup=get_tools_inline(),
        )
        return

    # ❌ Cancel pending order
    elif data == "orders_cancel_pending":
        pending = get_pending_order(user_id)
        if not pending:
            await safe_send(query, context, "No pending order found.")
            return

        order_id, _uid, order_code, status, desc, created_at = pending
        update_order_status(order_id, "cancelled")

        await safe_send(query, context, f"❌ Order {order_code} cancelled.")

        context.user_data.pop("orders_order_id", None)
        context.user_data.pop("orders_order_code", None)
        context.user_data.pop("orders_step", None)
        return

    # ✅ Proceed (global confirm) -> create order -> show Make Payment
    elif data == "orders_proceed":
        desc = context.user_data.get("order_pending_description", "Service")

        # Create order ONLY now
        order_id, order_code = create_order(user_id, description=desc)
        context.user_data["orders_order_id"] = order_id
        context.user_data["orders_order_code"] = order_code

        # Show Make Payment button next
        from handlers.payments import show_make_payment
        await show_make_payment(update, context, order_code)

        # cleanup
        context.user_data.pop("order_pending_description", None)
        return

    # ❌ Cancel (global confirm)
    elif data == "orders_cancel":
        await safe_send(query, context, "Order not created.")
        context.user_data.pop("order_pending_description", None)
        return

    # ⬅ Back inside orders
    elif data == "orders_back":
        await safe_send(query, context, "Orders:", reply_markup=get_orders_menu())
        return
