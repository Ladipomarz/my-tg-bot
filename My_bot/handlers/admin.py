import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from menus.admin_menu import get_admin_menu
from utils.db import get_paid_orders_for_admin, get_delivered_orders_for_admin

logger = logging.getLogger(__name__)

ADMIN_PAGE_SIZE = 7


def _is_admin(user_id: int, admin_ids: set[int]) -> bool:
    return user_id in admin_ids


def _admin_nav_kb(prefix: str, page: int, has_prev: bool, has_next: bool) -> list[list[InlineKeyboardButton]]:
    """
    Returns rows:
      - Back + Next on SAME ROW (when available)
      - Admin menu button row
    """
    rows: list[list[InlineKeyboardButton]] = []

    nav_row: list[InlineKeyboardButton] = []
    if has_prev:
        nav_row.append(InlineKeyboardButton("⬅ Back", callback_data=f"{prefix}:{page-1}"))
    if has_next:
        nav_row.append(InlineKeyboardButton("Next ➡", callback_data=f"{prefix}:{page+1}"))
    if nav_row:
        rows.append(nav_row)

    rows.append([InlineKeyboardButton("🏠 Admin Menu", callback_data="admin_menu")])
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

    # Admin main
    if data == "admin_menu":
        await q.edit_message_text("Admin menu:", reply_markup=get_admin_menu())
        return

    # Paid list
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

        text_lines = ["🟡 Paid / To Deliver"]
        kb_rows: list[list[InlineKeyboardButton]] = []

        if not rows:
            text_lines.append("\nNo orders right now.")
            kb_rows.extend(_admin_nav_kb("admin_paid", page, has_prev, has_next))
            await q.edit_message_text("\n".join(text_lines), reply_markup=InlineKeyboardMarkup(kb_rows))
            return

        for o in rows:
            code = (o.get("order_code") or "").strip()
            desc = (o.get("description") or "Service").strip()
            user_id = o.get("user_id")
            pay_status = (o.get("pay_status") or "").strip()

            text_lines.append(f"• {code} — {desc} (user {user_id}, {pay_status})")

            # Deliver button (handled by bot.py callback_router)
            kb_rows.append([
                InlineKeyboardButton(f"Deliver {code}", callback_data=f"admin_deliver:{code}")
            ])

        kb_rows.extend(_admin_nav_kb("admin_paid", page, has_prev, has_next))
        await q.edit_message_text("\n".join(text_lines), reply_markup=InlineKeyboardMarkup(kb_rows))
        return

    # Delivered list
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

        text_lines = ["📦 Delivered"]
        kb_rows: list[list[InlineKeyboardButton]] = []

        if not rows:
            text_lines.append("\nNo delivered orders yet.")
            kb_rows.extend(_admin_nav_kb("admin_delivered", page, has_prev, has_next))
            await q.edit_message_text("\n".join(text_lines), reply_markup=InlineKeyboardMarkup(kb_rows))
            return

        for o in rows:
            code = (o.get("order_code") or "").strip()
            desc = (o.get("description") or "Service").strip()
            user_id = o.get("user_id")
            text_lines.append(f"• {code} — {desc} (user {user_id})")

        kb_rows.extend(_admin_nav_kb("admin_delivered", page, has_prev, has_next))
        await q.edit_message_text("\n".join(text_lines), reply_markup=InlineKeyboardMarkup(kb_rows))
        return

    # Anything else: ignore here, bot.py handles admin_deliver:... etc.
    return
