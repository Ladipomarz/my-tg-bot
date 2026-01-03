import datetime
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from menus.orders_menu import (
    get_orders_menu,
    get_pending_order_menu,
    get_order_confirm_menu,
)
from menus.tools_menu import get_tools_inline
from utils.auto_delete import safe_send
from handlers.payments import show_make_payment

from utils.db import (
    create_order,
    get_pending_order,
    expire_pending_order_if_needed,
    update_order_status,
    get_orders_for_user,
    get_order_by_code,
)

logger = logging.getLogger(__name__)

PAGE_SIZE = 7


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
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔗 Open payment page", url=url)]]
    )


def history_kb(*, page: int, has_next: bool, has_prev: bool, delivered_files: list[tuple[str, str]]):
    """
    delivered_files: list of (order_code, filename) for delivered orders on this page

    Buttons:
      - One 'service.xxx' button per delivered order
      - Next/Back on same row
    """
    rows = []

    # File buttons (look like links)
    for order_code, filename in delivered_files:
        label = filename.strip() if filename else "service.txt"
        rows.append([InlineKeyboardButton(label, callback_data=f"order_file:{order_code}")])

    nav = []
    if has_prev:
        nav.append(InlineKeyboardButton("⬅ Back", callback_data=f"orders_history_page:{page-1}"))
    if has_next:
        nav.append(InlineKeyboardButton("Next ➡", callback_data=f"orders_history_page:{page+1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton("Back", callback_data="orders_back")])
    return InlineKeyboardMarkup(rows)


async def show_history(update_or_query, context: ContextTypes.DEFAULT_TYPE, user_id: int, page: int):
    """
    Clean paginated order history.
    - Shows delivered rows with [service.pdf]/[service.txt] and button(s).
    """
    # If your DB doesn't support offset, we paginate in Python:
    # fetch more and slice. This keeps it compatible.
    fetch_limit = (page + 1) * PAGE_SIZE + 1
    all_orders = get_orders_for_user(user_id, limit=fetch_limit)

    if not all_orders:
        await safe_send(update_or_query, context, "You have no orders yet.")
        return

    start = page * PAGE_SIZE
    end = start + PAGE_SIZE

    page_orders = all_orders[start:end]
    has_prev = page > 0
    has_next = len(all_orders) > end

    lines = ["Your orders:"]
    delivered_files: list[tuple[str, str]] = []

    for o in page_orders:
        status = (o.get("status") or "").lower().strip()
        pay_status = (o.get("pay_status") or "").lower().strip()
        delivery_status = (o.get("delivery_status") or "").lower().strip()

        code = (o.get("order_code") or "").strip()

        # User-facing mapping
        if status == "cancelled":
            emoji, label = "❌", "cancelled"
        elif status == "expired":
            emoji, label = "⌛️", "expired"
        elif delivery_status == "delivered":
            emoji, label = "📦", "delivered"
        elif pay_status in {"paid", "detected"}:
            emoji, label = "🟡", "payment received — processing"
        else:
            emoji, label = "🕒", "awaiting payment"

        # Delivered file display + button
        if delivery_status == "delivered":
            file_id = (o.get("delivery_file_id") or "").strip()
            filename = (o.get("delivery_filename") or "").strip() or "service.txt"

            if file_id:
                lines.append(f"{emoji} {code} — {label} [{filename}]")
                delivered_files.append((code, filename))
            else:
                lines.append(f"{emoji} {code} — {label}")
        else:
            lines.append(f"{emoji} {code} — {label}")

    kb = history_kb(page=page, has_next=has_next, has_prev=has_prev, delivered_files=delivered_files)
    await safe_send(update_or_query, context, "\n".join(lines), reply_markup=kb)


# ---------- GLOBAL CONFIRM HELPER ----------

async def ask_order_confirmation(update_or_query, context: ContextTypes.DEFAULT_TYPE, display_text: str, order_description: str):
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
    if not query or not query.data:
        return

    data = (query.data or "").strip()
    user_id = query.from_user.id

    # 🆕 New Order
    if data == "orders_new":
        pending = expire_pending_order_if_needed(user_id)

        if pending and pending.get("status") == "pending":
            pay_status = (pending.get("pay_status") or "").lower().strip()

            if pay_status in {"pending", "", "new"}:
                context.user_data["orders_order_id"] = pending["id"]
                context.user_data["orders_order_code"] = pending["order_code"]

                await safe_send(
                    query,
                    context,
                    _pending_text(pending),
                    reply_markup=get_pending_order_menu(),
                )
                return

            await safe_send(
                query,
                context,
                f"✅ Payment already detected for {pending['order_code']}.\nYour order is being processed.",
                reply_markup=get_tools_inline(),
            )
            return

        await safe_send(query, context, "Tools:", reply_markup=get_tools_inline())
        return

    # 📂 Order History
    if data == "orders_history":
        await show_history(query, context, user_id=user_id, page=0)
        return

    # 📂 History paging
    if data.startswith("orders_history_page:"):
        try:
            page = int(data.split(":", 1)[1])
            if page < 0:
                page = 0
        except Exception:
            page = 0
        await show_history(query, context, user_id=user_id, page=page)
        return

    # 📄 Re-send delivered file
    if data.startswith("order_file:"):
        order_code = data.split(":", 1)[1].strip()
        order = get_order_by_code(order_code)

        if not order:
            await safe_send(query, context, "❌ Order not found.")
            return

        if int(order.get("user_id") or 0) != int(user_id):
            await safe_send(query, context, "❌ You can’t access this order.")
            return

        delivery_status = (order.get("delivery_status") or "").lower().strip()
        file_id = (order.get("delivery_file_id") or "").strip()
        filename = (order.get("delivery_filename") or "service.txt").strip() or "service.txt"

        if delivery_status != "delivered" or not file_id:
            await safe_send(query, context, "❌ No delivered file available yet.")
            return

        # Re-send (persistent)
        await context.bot.send_document(
            chat_id=user_id,
            document=file_id,
            filename=filename,
            caption=f"📦 Re-sent {filename} for {order_code}",
        )
        return

    # ✅ Continue pending
    if data == "orders_continue":
        pending = expire_pending_order_if_needed(user_id)

        if not pending or pending.get("status") != "pending":
            await safe_send(query, context, "No active pending order.")
            return

        pay_status = (pending.get("pay_status") or "").lower().strip()
        if pay_status not in {"pending", "", "new"}:
            await safe_send(
                query,
                context,
                f"✅ Payment already detected for {pending['order_code']}.\nYour order is being processed.",
                reply_markup=get_tools_inline(),
            )
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

    # ✅ Proceed (Create new order)
    if data == "orders_proceed":
        desc = context.user_data.get("order_pending_description")

        if not desc:
            logger.warning("orders_proceed missing order_pending_description; defaulting to SSN Service")
            desc = "SSN Service"

        logger.info(
            "orders_proceed user_id=%s pending_desc=%r custom_price_usd=%r esim_email=%r",
            user_id,
            desc,
            context.user_data.get("custom_price_usd"),
            context.user_data.get("esim_email"),
        )

        order_id, order_code = create_order(
            user_id=user_id,
            description=desc,
            ttl_seconds=3600,
        )

        context.user_data["orders_order_id"] = order_id
        context.user_data["orders_order_code"] = order_code

        await show_make_payment(query, context, order_code)

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


async def debug_last_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    orders = get_orders_for_user(user_id)
    if not orders:
        await update.message.reply_text("No orders found for you.")
        return

    o = orders[0]
    msg = (
        "🧾 Last order:\n"
        f"Code: {o.get('order_code')}\n"
        f"Description: {o.get('description')}\n"
        f"Status: {o.get('status')}\n"
        f"Pay status: {o.get('pay_status')}\n"
        f"Delivery status: {o.get('delivery_status')}\n"
        f"Invoice: {o.get('invoice_url')}\n"
        f"Delivery file: {o.get('delivery_filename')}\n"
    )
    await update.message.reply_text(msg)
