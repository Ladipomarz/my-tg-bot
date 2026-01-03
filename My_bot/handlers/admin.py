import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from menus.admin_menu import get_admin_menu, get_admin_list_nav
from utils.db import get_paid_orders_for_admin, get_delivered_orders_for_admin

logger = logging.getLogger(__name__)

ADMIN_PAGE_SIZE = 7


def _is_admin(user_id: int, admin_ids: set[int]) -> bool:
    return user_id in admin_ids


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

    # Paid list page
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
                reply_markup=get_admin_list_nav("admin_paid", page, has_prev, has_next),
            )
            return

        text_lines = ["🟡 Paid / To Deliver"]
        kb_rows = []

        for o in rows:
            code = o.get("order_code")
            desc = (o.get("description") or "Service").strip()
            user_id = o.get("user_id")
            pay_status = (o.get("pay_status") or "").strip()

            text_lines.append(f"• {code} — {desc} (user {user_id}, {pay_status})")

            # Deliver button uses your existing deliver flow
            kb_rows.append([
                InlineKeyboardButton(f"Deliver {code}", callback_data=f"admin_deliver:{code}")
            ])

        # nav + back
        nav = get_admin_list_nav("admin_paid", page, has_prev, has_next)
        kb_rows.extend(nav.inline_keyboard)

        await q.edit_message_text("\n".join(text_lines), reply_markup=InlineKeyboardMarkup(kb_rows))
        return

    # Delivered list page
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
                reply_markup=get_admin_list_nav("admin_delivered", page, has_prev, has_next),
            )
            return

        lines = ["📦 Delivered"]
        for o in rows:
            code = o.get("order_code")
            desc = (o.get("description") or "Service").strip()
            user_id = o.get("user_id")
            lines.append(f"• {code} — {desc} (user {user_id})")

        await q.edit_message_text(
            "\n".join(lines),
            reply_markup=get_admin_list_nav("admin_delivered", page, has_prev, has_next),
        )
        return

    # For everything else (like admin_deliver:...), let your existing server logic handle it
    return
