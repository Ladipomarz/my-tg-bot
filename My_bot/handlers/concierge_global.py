import asyncio
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from utils.db import get_user_balance_usd
from utils.validator import normalize_global_country_name
from utils.auto_delete import safe_send, safe_delete_user_message, delete_tracked_message
from config import SUPPORT_HANDLE

logger = logging.getLogger(__name__)

# -----------------------------------------
# 🧠 THE SMART DICTIONARY
# Maps common abbreviations/slang to official names
# Add to this whenever users invent new ways to spell things
# -----------------------------------------
COUNTRY_ALIAS_MAP = {
    "uk": "United Kingdom",
    "england": "United Kingdom",
    "gb": "United Kingdom",
    "us": "United States",
    "usa": "United States",
    "uae": "United Arab Emirates",
    "dubai": "United Arab Emirates",
    "sa": "South Africa",
    "rsa": "South Africa",
    "nz": "New Zealand",
    "aus": "Australia",
}

# -----------------------------------------
# 🚪 1. THE ENTRY POINT
# Triggered when they click "Other Countries" -> "One Time"
# -----------------------------------------
async def start_concierge_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Clean up any previous menus
    chat_id = update.effective_chat.id
    await delete_tracked_message(context, chat_id, "otp_instruction_msg_id")
    
    # 2. Set the trap for the text router
    context.user_data["otp_step"] = "awaiting_manual_country"
    
    keyboard = [
        [InlineKeyboardButton("❌ Cancel", callback_data="back_main")]
    ]
    
    msg_text = (
        "🌍 <b>Global Routing Network</b>\n"
        "Initializing connection to international operators...\n\n"
        "📍 <b>Enter Target Country:</b>\n"
        "<i>(Type the country name below, e.g., Brazil, UK, India)</i>"
    )
    
    # 3. Send and track the message for the Janitor
    msg = await safe_send(
        update_or_query=update.callback_query or update,
        context=context,
        text=msg_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    
    if msg:
        context.user_data["otp_instruction_msg_id"] = msg.message_id


# -----------------------------------------
# -----------------------------------------
# 🎯 2. CATCHING THE COUNTRY INPUT
# -----------------------------------------
async def handle_manual_country(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    asyncio.create_task(safe_delete_user_message(update))
    
    user_text = (update.message.text or "").strip()
    if not user_text:
        return True

    # Use the new validator!
    is_valid, official_country = normalize_global_country_name(user_text)
    
    chat_id = update.effective_chat.id
    
    if not is_valid:
        # User typed garbage like 'ik' -> Reject them safely
        await delete_tracked_message(context, chat_id, "otp_instruction_msg_id")
        
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="back_main")]]
        msg = await safe_send(
            update_or_query=update, context=context,
            text=f"❌ <b>Country Not Found.</b>\nWe couldn't recognize <b>'{user_text}'</b>. Please type a valid country name.",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
        )
        if msg:
            context.user_data["otp_instruction_msg_id"] = msg.message_id
        return True

    # Valid country -> Proceed!
    context.user_data["concierge_country"] = official_country
    context.user_data["otp_step"] = "awaiting_manual_service"
    
    await delete_tracked_message(context, chat_id, "otp_instruction_msg_id")
    
    keyboard = [
        [InlineKeyboardButton("⬅ Back", callback_data="other_countries_start")],
        [InlineKeyboardButton("❌ Cancel", callback_data="back_main")]
    ]
    
    msg_text = (
        f"📍 <b>Target:</b> {official_country}\n\n"
        "💬 <b>Enter Target Service/App:</b>\n"
        "<i>(e.g., Telegram, WhatsApp, Tinder)</i>"
    )
    
    msg = await safe_send(
        update_or_query=update, context=context,
        text=msg_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
    )
    if msg:
        context.user_data["otp_instruction_msg_id"] = msg.message_id
        
    return True

# -----------------------------------------
# 💬 3. CATCHING THE SERVICE & SHOWING PRICE
# Triggered by text_router in bot.py
# -----------------------------------------
async def handle_manual_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    # 1. Zero-lag delete of their message
    asyncio.create_task(safe_delete_user_message(update))
    
    user_id = update.effective_user.id
    user_text = (update.message.text or "").strip().title()
    
    if not user_text:
        return True

    # 2. Save the service to memory
    context.user_data["concierge_service"] = user_text
    
    # 3. Get the Country they picked in Step 1
    official_country = context.user_data.get("concierge_country", "Unknown")
    
    # 4. Check their wallet balance
    current_balance = get_user_balance_usd(user_id)
    static_price = 8.00
    
    # 5. Build the summary screen
    chat_id = update.effective_chat.id
    await delete_tracked_message(context, chat_id, "otp_instruction_msg_id")
    
    # --- SCENARIO A: NOT ENOUGH MONEY ---
    if current_balance < static_price:
        shortfall = static_price - current_balance
        
        keyboard = [
            [InlineKeyboardButton("➕ Top up wallet", callback_data="wallet_menu")],
            [InlineKeyboardButton("❌ Cancel", callback_data="back_main")]
        ]
        
        msg_text = (
            "🧾 <b>Order Summary</b>\n\n"
            f"📍 <b>Country:</b> {official_country}\n"
            f"💬 <b>Service:</b> {user_text}\n"
            f"💎 <b>Price:</b> ${static_price:.2f}\n"
            f"💳 <b>Your Balance:</b> ${current_balance:.2f}\n\n"
            f"❌ <i>Insufficient balance.</i> Please top up exactly <b>${shortfall:.2f}</b> to proceed."
        )
        
        # We clear the step so they don't get stuck typing
        context.user_data.pop("otp_step", None)
        
    # --- SCENARIO B: THEY HAVE THE MONEY ---
    else:
        keyboard = [
            [InlineKeyboardButton("✅ Confirm & Pay $8.00", callback_data="concierge_pay")],
            [InlineKeyboardButton("❌ Cancel", callback_data="back_main")]
        ]
        
        msg_text = (
            "🧾 <b>Order Summary</b>\n\n"
            f"📍 <b>Country:</b> {official_country}\n"
            f"💬 <b>Service:</b> {user_text}\n"
            f"💎 <b>Price:</b> ${static_price:.2f}\n"
            f"💳 <b>Your Balance:</b> ${current_balance:.2f}\n\n"
            "⚡️ <i>Lines are allocated manually by our desk for maximum success rate.</i>\n"
            "Click confirm to securely process payment."
        )
        
        # We clear the text step so the bot waits for the button click
        context.user_data.pop("otp_step", None)

    # 6. Send it to the user
    msg = await safe_send(
        update_or_query=update,
        context=context,
        text=msg_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    
    if msg:
        context.user_data["otp_instruction_msg_id"] = msg.message_id

    return True



from utils.db import try_debit_user_balance_usd
from config import ADMIN_IDS

# -----------------------------------------
# 💳 4. PROCESS PAYMENT & ALERT ADMIN
# Triggered by 'concierge_pay' inline button
# -----------------------------------------
async def process_manual_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user_id = q.from_user.id
    
    country = context.user_data.get("concierge_country", "Unknown")
    service = context.user_data.get("concierge_service", "Unknown")
    static_price = 8.00
    
    # 1. Final Security Check: Try to debit the user
    if not try_debit_user_balance_usd(user_id, static_price):
        await q.answer("❌ Insufficient balance.", show_alert=True)
        return
        
    # 2. Update User UI (The Illusion of Automation)
    msg_text = (
        f"⚡️ <b>Payment Confirmed. (${static_price:.2f} Deducted)</b>\n\n"
        "🔄 <b>Executing routing protocol...</b>\n"
        f"Allocating a clean, high-trust line for <b>{country} ({service})</b>.\n\n"
        "<i>Please keep this menu open. Your encrypted number and OTP will be delivered to this chat shortly.</i>\n\n"
        "⏳ Status: <code>Agent assigned & Routing...</code>"
    )
    
    await q.edit_message_text(msg_text, parse_mode="HTML")
    
    # 3. Fire the loud alert to the Admin (You)
    admin_alert = (
        "🚨 <b>NEW GLOBAL CONCIERGE ORDER (PAID $8.00)</b> 🚨\n\n"
        f"👤 <b>User ID:</b> <code>{user_id}</code>\n"
        f"📍 <b>Country:</b> {country}\n"
        f"💬 <b>Service:</b> {service}\n\n"
        "🛠 <b>Action Required:</b>\n"
        "1. Buy the number on your provider.\n"
        "2. Click 'Direct Message Mode' in your Admin Menu to send the number to the User ID above.\n"
        "3. Send them the OTP when it arrives."
    )
    
    if ADMIN_IDS:
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=admin_alert, parse_mode="HTML")
            except Exception:
                pass
            
    # 4. Clear the session memory so they don't accidentally buy it twice
    context.user_data.pop("concierge_country", None)
    context.user_data.pop("concierge_service", None)