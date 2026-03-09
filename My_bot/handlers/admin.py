import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
import asyncio
from telegram import Update
from telegram.ext import CallbackContext
from utils.textverified_client import get_textverified_client
from config import ADMIN_IDS
import logging

logger = logging.getLogger(__name__)

import datetime
import os

from menus.admin_menu import get_admin_menu
from utils.helper import notify_admin
from utils.db import (
    get_paid_orders_for_admin, 
    get_delivered_orders_for_admin,
    get_order_by_code,
    set_delivery_status,
    set_order_status,
    add_user_balance_usd,
    get_connection
)

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

        codes = [(o.get("order_code") or "").strip() for o in rows if (o.get("order_code") or "").strip()]
        context.user_data["admin_paid_list"] = {"page": page, "codes": codes}

        text_lines = ["🟡 Paid / To Deliver"]
        for o in rows:
            code = (o.get("order_code") or "").strip()
            desc = (o.get("description") or "Service").strip()
            user_id = o.get("user_id")
            pay_status = (o.get("pay_status") or "").strip()
            text_lines.append(f"• {code} — {desc} (user {user_id}, {pay_status})")

        open_btns = [InlineKeyboardButton(f"Open {c}", callback_data=f"admin_open_paid:{c}") for c in codes]
        kb_rows: list[list[InlineKeyboardButton]] = []
        kb_rows.extend(_chunk_buttons(open_btns, per_row=2))
        kb_rows.extend(_admin_list_nav("admin_paid", page, has_prev, has_next))

        await q.edit_message_text("\n".join(text_lines), reply_markup=InlineKeyboardMarkup(kb_rows))
        return

    # -------------------------
    # DELIVERED LIST (paged)
    # Open -> admin_view:<code> (handled in bot.py)
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

        # ✅ Option A: go straight to payload view in bot.py
        open_btns = [InlineKeyboardButton(f"Delivered {c}", callback_data=f"admin_view:{c}") for c in codes]
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

        o = get_order_by_code(code) or {}

        desc = (o.get("description") or "Service").strip()
        user_id = o.get("user_id")
        pay_status = (o.get("pay_status") or "").strip()
        delivery_status = (o.get("delivery_status") or "").strip()
        order_type = (o.get("order_type") or "").strip()

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

        kb_rows = []
        
        # 🔀 THE ROUTING SPLIT
        if order_type == "premium_rental":
            # Premium Rental Buttons
            kb_rows.append([InlineKeyboardButton("✅ Done (Number Ready)", callback_data=f"admin_rental_done:{code}")])
            kb_rows.append([InlineKeyboardButton("❌ Cancel & Refund", callback_data=f"admin_rental_refund:{code}")])
        else:
            # Standard eSIM Button
            kb_rows.append([InlineKeyboardButton(f"✅ Deliver {code}", callback_data=f"admin_deliver:{code}")])

        if nav_row:
            kb_rows.append(nav_row)
            
        kb_rows.append([InlineKeyboardButton("⬅ Back to Paid List", callback_data=f"admin_paid:{lst.get('page', 0)}")])
        kb_rows.append([InlineKeyboardButton("⬅ Admin Menu", callback_data="admin_menu")])

        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rows))
        return

    # PREMIUM RENTAL: DONE LOGIC
    # -------------------------
    if data.startswith("admin_rental_done:"):
        code = data.split(":", 1)[1].strip()
        o = get_order_by_code(code)
        if not o:
            await q.answer("Order not found.")
            return
            
        user_id = o.get("user_id")
        desc = o.get("description", "Premium Service")
        
        # 1. Mark Delivered in DB
        set_delivery_status(o["id"], "delivered")
        
        # 2. Alert the User
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 <b>Your Premium Rental is Ready!</b>\n\n"
                     f"Your {desc} line is now active and ready to receive SMS.\n"
                     f"👉 Use the <b>/rentals</b> command to view your number.",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Could not alert user {user_id}: {e}")
            await notify_admin(f"couldnt alert user: {e}")
            
            
            
        # 3. Update Admin Screen
        await q.edit_message_text(f"✅ Order <b>{code}</b> marked as Delivered. User notified.", parse_mode="HTML")
        return

    # -------------------------
    # PREMIUM RENTAL: CANCEL LOGIC
    # -------------------------
    if data.startswith("admin_rental_refund:"):
        code = data.split(":", 1)[1].strip()
        o = get_order_by_code(code)
        if not o:
            await q.answer("Order not found.")
            return
            
        user_id = o.get("user_id")
        amount = float(o.get("amount_usd") or 0.0)
        
        # 1. Cancel in DB & Refund Wallet
        set_order_status(o["id"], "cancelled")
        add_user_balance_usd(user_id, amount)
        
        # 2. Alert the User
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ <b>Rental Cancelled.</b>\n\n"
                     f"We apologize, but our provider is currently out of stock for this specific long-term line.\n"
                     f"💰 <b>${amount:.2f}</b> has been instantly refunded to your wallet.",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Could not alert user {user_id}: {e}")
            await notify_admin(f"couldnt alert user: {e}")
            
        # 3. Update Admin Screen
        await q.edit_message_text(f"❌ Order <b>{code}</b> Cancelled. <b>${amount:.2f}</b> refunded to user.", parse_mode="HTML")
        return

    # Anything else: do nothing here (bot.py handles the rest)
    return



async def fix_db_sequence(update, context):
    """Temporary command to resync the PostgreSQL ID counter."""
    # This SQL command fast-forwards the sequence to match the highest ID in the table
    query = "SELECT setval(pg_get_serial_sequence('active_rentals', 'id'), coalesce(max(id),0) + 1, false) FROM active_rentals;"
    
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
            conn.commit()
        await update.message.reply_text("✅ Database ID counter successfully resynced!")
    except Exception as e:
        await update.message.reply_text(f"💥 Error fixing sequence: {e}")
       
        
        
async def rescue_my_number(update, context):
    """Temporary command to inject a test number directly into the DB."""

    # 1. Your exact hardcoded test data
    user_id = 3334566533
    rental_id = "expwer"
    phone_number = "3445553340"
    service_name = "second test"
    
    # 2. Set expiration for 2 minutes from now
    expiration_date = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=1)
    
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # 🚀 STEP 1: RESCUE THE USER (The "Parent")
                # This ensures user 2222222222 exists so the Foreign Key doesn't crash
                cur.execute("""
                    INSERT INTO users (user_id, balance_usd) 
                    VALUES (%s, 0.00) 
                    ON CONFLICT (user_id) DO NOTHING
                """, (user_id,))

                # 🚀 STEP 2: INJECT THE RENTAL (The "Child")
                query = """
                    INSERT INTO active_rentals 
                    (user_id, rental_id, phone_number, service_name, always_on, is_renewable, status, expiration_time)
                    VALUES (%s, %s, %s, %s, %s, %s, 'active', %s)
                    ON CONFLICT (rental_id) DO NOTHING
                """
                cur.execute(
                    query, 
                    (user_id, rental_id, phone_number, service_name, False, False, expiration_date)
                )
            conn.commit()
            
        # 3. Dynamic Alarm Calculation
        now = datetime.datetime.now(datetime.timezone.utc)
        delay_seconds = (expiration_date - now).total_seconds()
        
        if context.job_queue and delay_seconds > 0:
            from handlers.rental import scheduled_expire_rental 
            context.job_queue.run_once(
                scheduled_expire_rental,
                when=delay_seconds,
                data={"rental_id": rental_id, "user_id": user_id},
                name=f"expire_{rental_id}"
            )

        await update.message.reply_text(
            f"✅ <b>RESCUE SUCCESS!</b>\n\n"
            f"User <code>{user_id}</code> created and number <code>{phone_number}</code> injected.\n"
            f"💀 It will expire in <b>120 seconds</b>.",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Rescue failed: {e}")
        await update.message.reply_text(f"💥 Error: {e}")
                

async def admin_check_balance(update: Update, context: CallbackContext):
    """Handles the 'Check Balance' button in the Admin Menu."""
    query = update.callback_query
    await query.answer()

    try:
        # 1. Connect to TextVerified Client
        client, _, _, _, _, _, _ = get_textverified_client()
        
        # 2. Correct Method: client.account.me()
        account_info = await asyncio.to_thread(client.account.me)
        
        # 3. Extract the 'current_balance' attribute
        balance = getattr(account_info, "current_balance", 0.0)

        msg = (
            f"💳 <b>TextVerified API Wallet</b>\n\n"
            f"<b>Current Balance:</b> ${balance:.2f}\n\n"
            f"<i>Ensure you keep this above $5.00 for auto-extensions.</i>"
        )
        await query.edit_message_text(text=msg, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"Failed to fetch API balance: {e}")
        await query.edit_message_text(text=f"❌ <b>API Error:</b> {e}", parse_mode="HTML")
        

async def admin_get_stats(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM users;")
                u_count = cur.fetchone()[0]
                
                cur.execute("SELECT COUNT(*) FROM active_rentals;")
                a_count = cur.fetchone()[0]
                
                cur.execute("SELECT COUNT(*) FROM expired_rentals;")
                e_count = cur.fetchone()[0]

        msg = (
            f"📊 <b>System Health Stats</b>\n\n"
            f"👥 <b>Total Users:</b> {u_count}\n"
            f"🟢 <b>Live Rentals:</b> {a_count}\n"
            f"📦 <b>Archived History:</b> {e_count}\n"
        )
        await query.edit_message_text(text=msg, parse_mode="HTML")
    except Exception as e:
        await query.edit_message_text(text=f"❌ Error: {e}")     