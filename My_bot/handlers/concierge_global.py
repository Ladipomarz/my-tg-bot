import asyncio
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from utils.db import get_user_balance_usd,try_debit_user_balance_usd
from utils.validator import normalize_global_country_name,_GLOBAL_NORM_TO_CANON
from utils.auto_delete import safe_send, safe_delete_user_message, delete_tracked_message
from config import SUPPORT_HANDLE

logger = logging.getLogger(__name__)

# -----------------------------------------
async def start_concierge_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Clean up previous menu
    chat_id = update.effective_chat.id
    await delete_tracked_message(context, chat_id, "otp_instruction_msg_id")
    
    # 2. Set the trap for the text router
    context.user_data["otp_step"] = "awaiting_manual_country"
    
    # 3. Keyboard with Back and Cancel
    keyboard = [
        [InlineKeyboardButton("⬅ Back", callback_data="other_countries_start")],
        [InlineKeyboardButton("❌ Cancel", callback_data="back_main")]
    ]
    
    msg_text = (
        "🌍 <b>Global Routing Network</b>\n"
        "Initializing connection to international operators...\n\n"
        "📍 <b>Enter Target Country:</b>\n"
        "<i>(Type the country name below, e.g., Brazil, India)</i>"
    )
    
    # 4. Send and track for the Janitor
    msg = await safe_send(
        update_or_query=update.callback_query or update,
        context=context,
        text=msg_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    
    if msg:
        context.user_data["otp_instruction_msg_id"] = msg.message_id


# 🎯 2. CATCHING THE COUNTRY INPUT
async def handle_manual_country(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    asyncio.create_task(safe_delete_user_message(update))
    
    user_text = (update.message.text or "").strip()
    if not user_text:
        return True
    
    chat_id = update.effective_chat.id

    # 🚨 1. THE USA TRAP MUST BE ABSOLUTELY FIRST 🚨
    usa_variants = ["us", "usa", "america", "united states", "united state", "u.s.a", "u.s"]
    if user_text.lower() in usa_variants:
        await delete_tracked_message(context, chat_id, "otp_instruction_msg_id")
        
        keyboard = [[InlineKeyboardButton("🇺🇸 Go to USA Menu", callback_data="otp_usa")]]
        msg = await safe_send(
            update_or_query=update, context=context,
            text="🇺🇸 <b>Dedicated USA Service Detected</b>\n\nFor United States numbers, please use our dedicated USA menu for lower rates.",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
        )
        if msg:
            context.user_data["otp_instruction_msg_id"] = msg.message_id
        return True

    # 2. VALIDATE AGAINST YOUR 180+ COUNTRY LIST
    is_valid, official_country = normalize_global_country_name(user_text)
    
    if is_valid:
        # Check if they typed an exact match/alias, or if the bot had to auto-correct a typo
        if user_text.lower() not in _GLOBAL_NORM_TO_CANON:
            # 🚨 THE BOT CAUGHT A TYPO (e.g., "bazil") -> Ask for confirmation
            await delete_tracked_message(context, chat_id, "otp_instruction_msg_id")
            
            keyboard = [
                # Notice how we reuse the g_quick_ logic so clicking "Yes" instantly asks for the Service!
                [InlineKeyboardButton(f"✅ Yes, {official_country}", callback_data=f"g_quick_{official_country}")],
                [InlineKeyboardButton("❌ No, Try Again", callback_data="other_countries_manual")]
            ]
            
            msg = await safe_send(
                update_or_query=update, 
                context=context,
                text=f"🤔 <b>Did you mean {official_country}?</b>\n\nWe couldn't find an exact match for '{user_text}'.",
                reply_markup=InlineKeyboardMarkup(keyboard), 
                parse_mode="HTML"
            )
            if msg:
                context.user_data["otp_instruction_msg_id"] = msg.message_id
            return True
            
        else:
            # ✅ EXACT MATCH (e.g., "brazil" or "uk") -> Proceed normally
            context.user_data["concierge_country"] = official_country
            context.user_data["otp_step"] = "awaiting_manual_service"
            await ask_for_service(update, context, official_country)
            return True

    # 3. IF COMPLETELY INVALID (e.g., "narnia")
    if not is_valid:
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
            f"Click confirm to securely process payment."
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


# -----------------------------------------
# 💳 4. PROCESS PAYMENT & ALERT ADMIN
# Triggered by 'concierge_pay' inline button
# -----------------------------------------
# Inside handlers/concierge_global.py

async def process_manual_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user_id = q.from_user.id
    chat_id = q.message.chat_id
    
    country = context.user_data.get("concierge_country", "Unknown")
    service = context.user_data.get("concierge_service", "Unknown")
    static_price = 8.00
    
    # 1. Final Security Check: Try to debit the user
    if not try_debit_user_balance_usd(user_id, static_price):
        await q.answer("❌ Insufficient balance.", show_alert=True)
        return
        
    # 2. THE ILLUSION: Use safe_send and track the ID
    msg_text = (
        f"⚡️ <b>Payment Confirmed. (${static_price:.2f} Deducted)</b>\n\n"
        "🔄 <b>Executing routing protocol...</b>\n"
        f"Allocating a clean, high-trust line for <b>{country} ({service})</b>.\n\n"
        "<i>Your encrypted number and OTP will be delivered to this chat shortly.</i>\n\n"
        "⏳ Status: <code>Number assigned & Routing...</code>"
    )
    
    # Clean up the previous "Order Summary" message
    await delete_tracked_message(context, chat_id, "otp_instruction_msg_id")

    # Send the success message
    msg = await safe_send(
        update_or_query=q,
        context=context,
        text=msg_text,
        parse_mode="HTML"
    )
    
    # Save ID for the Janitor to clean up later
    if msg:
        context.user_data["otp_instruction_msg_id"] = msg.message_id
    
    
# handlers/concierge_global.py

def get_concierge_back_keyboard():
    """Centralized UI for the Concierge flow"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅ Back", callback_data="other_countries_start")],
        [InlineKeyboardButton("❌ Cancel", callback_data="back_main")]
    ])

async def ask_for_service(update: Update, context: ContextTypes.DEFAULT_TYPE, country_name: str):
    """The actual UI sender—no logic, just sending the message"""
    chat_id = update.effective_chat.id
    await delete_tracked_message(context, chat_id, "otp_instruction_msg_id")
    
    msg_text = (
        f"📍 <b>Target:</b> {country_name}\n\n"
        "💬 <b>Enter Target Service/App:</b>\n"
        "<i>(e.g., Telegram, WhatsApp, Tinder)</i>"
    )
    
    msg = await safe_send(
        update_or_query=update.callback_query or update,
        context=context,
        text=msg_text,
        reply_markup=get_concierge_back_keyboard(),
        parse_mode="HTML"
    )
    
    if msg:
        context.user_data["otp_instruction_msg_id"] = msg.message_id    