import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from menus.admin_menu import get_admin_menu
from utils.db import get_paid_orders_for_admin, get_delivered_orders_for_admin

logger = logging.getLogger(__name__)

ADMIN_PAGE_SIZE = 7


def _is_admin(user_id: int, admin_ids: set[int]) -> bool:
    return user_id in admin_ids


def _chunk_buttons(btns: list[InlineKeyboardButton], per_row: int = 2) -> list[list[InlineKeyboardButton]]:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for b in btns:
        row.append(b)
        if len(row) == per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def _admin_list_nav(kind: str, page: int, has_prev: bool, has_next: bool) -> list[list[InlineKeyboardButton]]:
    nav_row: list[InlineKeyboardButton] = []
    if has_prev:
        nav_row.append(InlineKeyboardButton("⬅ Prev", callback_data=f"{kind}:{page-1}"))
    if has_next:
        nav_row.append(InlineKeyboardButton("Next ➡", callback_data=f"{kind}:{page+1}"))
    rows: list[list[InlineKeyboardButton]] = []
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton("⬅ Admin Menu", callback_data="admin_menu")])
    return rows


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE, admin_ids: set[int]):
    uid = update.effective_user.id
    if not _is_admin(uid, admin_ids):
        return
    await update.message.reply_text("Admin menu:", reply_markup=get_admin_menu())


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, admin_ids: set[int]):
    q = update.callback_query
    if not q or not q.data:
        return

    uid = q.from_user.id
    if not _is_admin(uid, admin_ids):
        try:
            await q.edit_message_text("❌ Not authorized.")
        except Exception:
            pass
        return

    data = (q.data or "").strip()

    # -------------------------
    # Admin main menu
    # -------------------------
    if data == "admin_menu":
        await q.edit_message_text("Admin menu:", reply_markup=get_admin_menu())
        return

    # -------------------------
    # PAID LIST (paged)
    # -------------------------
    if data.startswith("admin_paid:"):
        try:
            page = int(data.split(":", 1)[1])
            if page < 0:
                page = 0
        except Exception:
            page = 0

        offset = page * ADMIN_PAGE_SIZE
        rows = get_paid_orders_for_admin(limit=ADMIN_PAGE_SIZE + 1, offset=offset)
        has_next = len(rows) > ADMIN_PAGE_SIZE
        rows = rows[:ADMIN_PAGE_SIZE]
        has_prev = page > 0

        if not rows:
            await q.edit_message_text(
                "🟡 Paid / To Deliver\n\nNo orders right now.",
                reply_markup=InlineKeyboardMarkup(_admin_list_nav("admin_paid", page, has_prev, has_next)),
            )
            return

        # Save “current list” so Prev/Next works in the order detail screen
        codes = [(o.get("order_code") or "").strip() for o in rows if (o.get("order_code") or "").strip()]
        context.user_data["admin_paid_list"] = {
            "page": page,
            "codes": codes,
        }

        # Text list
        text_lines = ["🟡 Paid / To Deliver"]
        for o in rows:
            code = (o.get("order_code") or "").strip()
            desc = (o.get("description") or "Service").strip()
            user_id = o.get("user_id")
            pay_status = (o.get("pay_status") or "").strip()
            text_lines.append(f"• {code} — {desc} (user {user_id}, {pay_status})")

        # Buttons: OPEN (2 per row)
        open_btns = [InlineKeyboardButton(f"Open {c}", callback_data=f"admin_open_paid:{c}") for c in codes]
        kb_rows: list[list[InlineKeyboardButton]] = []
        kb_rows.extend(_chunk_buttons(open_btns, per_row=2))
        kb_rows.extend(_admin_list_nav("admin_paid", page, has_prev, has_next))

        await q.edit_message_text("\n".join(text_lines), reply_markup=InlineKeyboardMarkup(kb_rows))
        return

    # -------------------------
    # DELIVERED LIST (paged) (optional open)
    # -------------------------
    if data.startswith("admin_delivered:"):
        try:
            page = int(data.split(":", 1)[1])
            if page < 0:
                page = 0
        except Exception:
            page = 0

        offset = page * ADMIN_PAGE_SIZE
        rows = get_delivered_orders_for_admin(limit=ADMIN_PAGE_SIZE + 1, offset=offset)
        has_next = len(rows) > ADMIN_PAGE_SIZE
        rows = rows[:ADMIN_PAGE_SIZE]
        has_prev = page > 0

        if not rows:
            await q.edit_message_text(
                "📦 Delivered\n\nNo delivered orders yet.",
                reply_markup=InlineKeyboardMarkup(_admin_list_nav("admin_delivered", page, has_prev, has_next)),
            )
            return

        codes = [(o.get("order_code") or "").strip() for o in rows if (o.get("order_code") or "").strip()]
        context.user_data["admin_delivered_list"] = {"page": page, "codes": codes}

        lines = ["📦 Delivered"]
        for o in rows:
            code = (o.get("order_code") or "").strip()
            desc = (o.get("description") or "Service").strip()
            user_id = o.get("user_id")
            lines.append(f"• {code} — {desc} (user {user_id})")

        open_btns = [InlineKeyboardButton(f"Open {c}", callback_data=f"admin_open_delivered:{c}") for c in codes]
        kb_rows: list[list[InlineKeyboardButton]] = []
        kb_rows.extend(_chunk_buttons(open_btns, per_row=2))
        kb_rows.extend(_admin_list_nav("admin_delivered", page, has_prev, has_next))

        await q.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb_rows))
        return

    # -------------------------
    # OPEN ORDER (PAID LIST VIEW)
    # -------------------------
    if data.startswith("admin_open_paid:"):
        code = data.split(":", 1)[1].strip()
        lst = context.user_data.get("admin_paid_list") or {}
        codes = lst.get("codes") or []

        try:
            idx = codes.index(code)
        except Exception:
            idx = 0

        # You already have get_order_by_code in bot.py; easiest is to import it here if you want.
        # If you prefer not to import, keep detail view minimal.
        from utils.db import get_order_by_code
        o = get_order_by_code(code) or {}

        desc = (o.get("description") or "Service").strip()
        user_id = o.get("user_id")
        pay_status = (o.get("pay_status") or "").strip()
        delivery_status = (o.get("delivery_status") or "").strip()

        text = (
            "🧾 Order Details\n\n"
            f"Order: {code}\n"
            f"User: {user_id}\n"
            f"Service: {desc}\n"
            f"Pay: {pay_status}\n"
            f"Delivery: {delivery_status}\n"
        )

        nav_row = []
        if idx > 0:
            nav_row.append(InlineKeyboardButton("◀ Prev", callback_data=f"admin_open_paid:{codes[idx-1]}"))
        if idx < len(codes) - 1:
            nav_row.append(InlineKeyboardButton("Next ▶", callback_data=f"admin_open_paid:{codes[idx+1]}"))

        kb_rows = [
            [InlineKeyboardButton(f"✅ Deliver {code}", callback_data=f"admin_deliver:{code}")],
        ]
        if nav_row:
            kb_rows.append(nav_row)
        kb_rows.append([InlineKeyboardButton("⬅ Back to Paid List", callback_data=f"admin_paid:{lst.get('page', 0)}")])
        kb_rows.append([InlineKeyboardButton("⬅ Admin Menu", callback_data="admin_menu")])

        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rows))
        return

    # -------------------------
    # OPEN ORDER (DELIVERED LIST VIEW) – no deliver button
    # -------------------------
    if data.startswith("admin_open_delivered:"):
        kb_rows.insert(0, [InlineKeyboardButton("✏️ Edit & Resend", callback_data=f"admin_edit:{code}")])
        code = data.split(":", 1)[1].strip()
        lst = context.user_data.get("admin_delivered_list") or {}
        codes = lst.get("codes") or []

        try:
            idx = codes.index(code)
        except Exception:
            idx = 0

        from utils.db import get_order_by_code
        o = get_order_by_code(code) or {}

        desc = (o.get("description") or "Service").strip()
        user_id = o.get("user_id")
        delivered_at = o.get("delivered_at")
        fname = (o.get("delivery_filename") or "").strip()

        text = (
            "📦 Delivered Order\n\n"
            f"Order: {code}\n"
            f"User: {user_id}\n"
            f"Service: {desc}\n"
            f"Delivered at: {delivered_at}\n"
            f"File: {fname}\n"
        )

        nav_row = []
        if idx > 0:
            nav_row.append(InlineKeyboardButton("◀ Prev", callback_data=f"admin_open_delivered:{codes[idx-1]}"))
        if idx < len(codes) - 1:
            nav_row.append(InlineKeyboardButton("Next ▶", callback_data=f"admin_open_delivered:{codes[idx+1]}"))

        kb_rows = []
        if nav_row:
            kb_rows.append(nav_row)
        kb_rows.append([InlineKeyboardButton("⬅ Back to Delivered List", callback_data=f"admin_delivered:{lst.get('page', 0)}")])
        kb_rows.append([InlineKeyboardButton("⬅ Admin Menu", callback_data="admin_menu")])

        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rows))
        return

    # Anything else: do nothing here (your bot.py handles admin_deliver wizard)
    return

