import datetime
import os
import re
import asyncio
from telegram import Update
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext,ConversationHandler
from handlers.otp_handler import send_services_txt, _area_codes_for_state
from utils.validator import US_STATE_NAMES,suggest_us_states_full_name
from pricelist import RENEWAL_BASE_PRICES, RENEWAL_UNIVERSAL_PRICES,UNIVERSAL_RENTAL_PRICES
import random
import requests
import html
import httpx
import time
from utils.auto_delete import safe_send
from utils.textverified_client import get_textverified_client
from utils.helper import notify_admin
from pricelist import get_rental_price_usd
from utils.db import (
    get_rental_service_name_by_code,
    save_active_rental,
    get_user_active_rentals,
    get_rental_details,
    try_debit_user_balance_usd, 
    add_user_balance_usd,
    get_user_balance_usd,
    extend_rental_timer,
    create_order,
    update_payment_status_by_order_code, 
    set_delivery_status,
    set_order_status,
    mark_rental_expired,
    auto_expire_rentals,

)

from telegram.constants import ParseMode
from config import ADMIN_IDS,SUPPORT_HANDLE

import logging
logger = logging.getLogger(__name__)

# This is for validating the Product ID and transitioning to the next step

async def handle_rental_product_id(update: Update, context: CallbackContext):
    """
    Handles the rental product ID input and asks for the state where the rental number will be generated.
    """
    # Check if it's a callback query (which is the case when the user clicks on "Yes, I have the Product ID")
    if update.callback_query:
        context.user_data["otp_step"] = "awaiting_rental_product_id"  # Indicate that we are waiting for the product ID

        # Send the message asking for the product ID
        await safe_send(
            update,
            context,
            "✅ Great. Please reply with the 4-digit Product ID (example: 0042)."
        )

        # Acknowledge the callback query to avoid waiting for it
        await update.callback_query.answer()
        return  # Stop here, the next step is when the user replies with the Product ID

    # If it's a regular message, we handle the product ID input
    if update.message:
        product_id = update.message.text.strip()  # Capture the Product ID
        
        # ✅ THE FIX: Look up the real service name from your Rental Database!
        service_name = get_rental_service_name_by_code(product_id)
        
        if not service_name:
            await safe_send(update, context, "❌ Invalid Product ID. Please check the Rental Services list.")
            return

        # Validate the Product ID
        # Validate the Product ID
        if len(product_id) in [3,4] and product_id.isdigit():
            
            # 👇 THE 1-DAY MANUAL ENTRY BLOCKER 👇
            duration_api = context.user_data.get("otp_duration_api", "ONE_DAY")
            is_universal = any(keyword in service_name.lower() for keyword in ["universal", "general", "not listed", "servicenotlisted", "allservices"])
            
            if is_universal and duration_api == "ONE_DAY":
                await safe_send(
                    update, 
                    context, 
                    " <b>Minimum Duration Required</b>\n\nPremium Universal (All-Services) numbers require a minimum rental period of <b>3 Days</b>.\n\n<i>Please restart and select a longer duration.</i>", 
                    parse_mode="HTML"
                )
                context.user_data.pop("otp_step", None)
                return
            # 👆 END OF BLOCKER 👆

            context.user_data["otp_service_name"] = service_name
            context.user_data["otp_rental_product_id"] = product_id  
            context.user_data["otp_step"] = "awaiting_rental_state" 
            
            await ask_state_or_random(update, context)
            
        else:
            # If the Product ID is invalid
            await safe_send(update, context, "❌ Invalid Product ID. Please reply with a valid 4-digit Product ID (e.g. 0123).")


async def ask_state_or_random(update: Update, context: CallbackContext):
    """
    Ask the user if they want the number generated from a specific US state, and show prices.
    """
    context.user_data["otp_step"] = "awaiting_state_or_random"
    
    # 🕵️ THE FIX: Identify the source (Message or Button)
    if update.message:
        # User typed the ID
        target = update.message
    else:
        # User clicked the Universal button
        target = update.callback_query.message

    # --- 💰 DYNAMIC PRICING CHECK ---
    # Grab the service and duration they ALREADY chose earlier
    service = context.user_data.get("otp_service_name", "Unknown")
    duration_api = context.user_data.get("otp_duration_api", "ONE_DAY") # ONE_DAY is just a fallback to prevent crashes

    # Calculate the normal price
    price_random = get_rental_price_usd(service, duration_api, "Random")
    
    # Calculate the premium price (We pass "NY" just to trigger your state fee in the calculator)
    price_specific = get_rental_price_usd(service, duration_api, "NY")
    # ---------------------------------

    # Send the prompt using the correct target with dynamic prices
    await safe_send(
        update,
        context,
        f"Do you want the number to be generated from a specific US state?\n\n"
        f"<b>Specific State Price : ${price_specific:.2f}</b>\n\n"
        f"<b>Random state price: ${price_random:.2f}</b>\n\n"
        f"✅ Reply with: <b>yes</b> or <b>no</b>",
        parse_mode="HTML"
    )
    
async def handle_state_or_random(update: Update, context: CallbackContext):
    """
    Handle the user's response for state or random selection.
    """
    response = update.message.text.strip().lower()

    if response == "yes":
        # If user wants to specify the state
        context.user_data["otp_step"] = "awaiting_state"
        await safe_send(
            update,
            context,
            "Please enter the US state you want the rental number generated from (e.g., California)."
        )
    elif response == "no":
        # If user does not want to specify the state, pick a random state
        context.user_data["otp_step"] = "random_state"
        # Randomly choose a state 
        context.user_data["otp_state"] = "Random"

        # Proceed to final confirmation
        await final_confirmation(update, context)
    else:
        # If the input is invalid, prompt the user again
        await safe_send(update,context, "❌ Please reply with either 'yes' or 'no' to confirm.")   

                        
            
async def handle_rental_state(update: Update, context: CallbackContext):
    state = update.message.text.strip()
    
    # Normalize the input state (convert to lowercase and remove extra spaces)
    state = state.lower()

    # Validate the state (match it with valid states)
    valid_states = [state.lower() for state in US_STATE_NAMES]  # Normalize all valid states to lowercase
    

    if state in valid_states:
        context.user_data["otp_state"] = state
        # Proceed to final confirmation
        await final_confirmation(update, context)
    else:
        
        await safe_send(update, context, "❌ Invalid state. Please provide a valid state (e.g., California).")

        # If invalid, suggest valid states
        suggestions = suggest_us_states_full_name(state)
        suggestion_text = "Did you mean:\n" + "\n".join(suggestions) if suggestions else "❌ Invalid state. Please provide a valid state (e.g., California)."
        await safe_send(update, context, suggestion_text)



async def final_confirmation(update: Update, context: CallbackContext):
    """
    Display the final confirmation with strict price validation.
    """
    service = context.user_data.get("otp_service_name", "Unknown Service")
    state = context.user_data.get("otp_state", "Random")
    duration_api = context.user_data.get("otp_duration_api") # No default here either!

    target = update.message if update.message else update.callback_query.message
    
    try:
        # 1. Ask for the strict price. If they glitch the duration, this will crash gracefully.
        price = get_rental_price_usd(service, duration_api, state)
        
        # 2. SAVE THE FINAL PRICE TO MEMORY! (Crucial for the wallet debit)
        context.user_data["rental_price"] = price

        confirmation_message = f"""
FINAL CONFIRMATION:

Service: {service}
State: {state}
Price: ${price:.2f}

 Please reply with either 'yes' or 'no' to confirm.
"""
        await safe_send(update, context, confirmation_message)
        context.user_data["otp_step"] = "rental_final_confirm" 
        
    except ValueError as e:
        # 3. IF PRICING FAILS, REJECT THE USER
        await safe_send( update, context, "❌Invalid duration or service selected. Please restart your purchase.")
        context.user_data.pop("otp_step", None)
        
async def confirm_rental(update: Update, context: CallbackContext):
    """
    Handles the final 'yes' or 'no', debits the wallet safely, and buys the API number.
    """
    target = update.message if update.message else update.callback_query.message
    text = target.text.strip().lower()
    
    # 🧹 MAGICAL VANISH: Instantly delete the user's "yes" or "no" message
    if update.message:
        try:
            await update.message.delete()
        except Exception as e:
            logger.error(f"Failed to Pass here {admin_id}: {e}")
            await notify_admin(f"Failed to Pass here: {e}")
            pass

    if text not in ['yes', 'no']:
        await safe_send(update, context, " Please reply with exactly 'yes' or 'no'.")
        return

    # If they say no, safely cancel and wipe the memory
    if text == 'no':
        await safe_send(update, context,"✅ Rental cancelled.")
        context.user_data.pop("otp_step", None)
        return

    # Grab variables
    user_id = update.effective_user.id
    price = context.user_data.get("rental_price", 0.0)
    service = context.user_data.get("otp_service_name")
    state = context.user_data.get("otp_state")
    duration_api = context.user_data.get("otp_duration_api")
    always_on = context.user_data.get("otp_always_on", True)
    is_renewable = context.user_data.get("otp_is_renewable", False)

    # UI Loading message
    processing_msg = await target.reply_text("⏳ Securing funds and fetching your premium number...")
        
    # 3. 🛡️ THE ESCROW HOLD (Wallet Deduction)
    if not try_debit_user_balance_usd(user_id, price):
        try:
            await processing_msg.delete()
        except Exception:
            pass
        
        # EXACT PIPELINE FROM OTP_HANDLER WITH REMAINDER MATH
        bal = get_user_balance_usd(user_id)
        remainder = price - bal  # Calculate exactly how much they are missing
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Top up wallet", callback_data="wallet_topup")],
        ])
        
        await safe_send(
            update,
            context,
            f"❌ Insufficient wallet balance.\n"
            f"Price: ${price:.2f}\n"
            f"Your balance: ${bal:.2f}\n\n"
            f"Please top up your wallet with <b>${remainder:.2f}</b> and try again.",
            reply_markup=kb,
            parse_mode="HTML"
        )
        context.user_data.pop("otp_step", None)
        return

    # 📦 --- LOG THE RENTAL TO THE ORDERS DATABASE --- 📦
    duration_text = context.user_data.get('otp_duration_text', duration_api)
    state_display = state if state and state.lower() != "random" else "Random"
    desc = f"Rental: {service} ({duration_text}) [State: {state_display}]"
    
    order_id, order_code = create_order(
        user_id=user_id,
        description=desc,
        ttl_seconds=31536000,  # 1 year TTL
        amount_usd=price,
        order_type="premium_rental"
    )
    
    # Marks it paid so it shows in the UI immediately
    update_payment_status_by_order_code(order_code, pay_status="paid")
    # --------------------------------------------------------

    # 🛑 THE CONCIERGE BYPASS FOR MASSIVE PACKAGES 🛑
    concierge_durations = ["THREE_MONTHS", "SIX_MONTHS", "NINE_MONTHS", "ONE_YEAR", "FOREVER"]
    
    if duration_api in concierge_durations:
        try:
            await processing_msg.delete()
        except Exception:
            pass
            
        # 1. Alert the User
        await safe_send(
            update,
            context,
            f"✅ <b>Payment Secured! (${price:.2f})</b>\n\n"
            f"Because you selected a massive <b>{duration_text}</b> package, your dedicated line is being manually provisioned by our admin team for the highest quality.\n\n"
            f"<i>Please allow up to 24 hours. You can track the status of this number directly in your <b>Orders</b> menu.</i>",
            parse_mode="HTML"
        )
        
        # 2. Alert the Admin (THE FIX: Safe loop through all admins)
        if ADMIN_IDS:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🛠 Manage Order", callback_data=f"admin_open_paid:{order_code}")
            ]])
            
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=f"🚨 <b>MANUAL RENTAL ORDER!</b>\n\n"
                             f"Order: <code>{order_code}</code>\n"
                             f"User: <code>{user_id}</code>\n"
                             f"Service: {service}\n"
                             f"Duration: {duration_api}\n"
                             f"Paid: ${price:.2f}\n\n"
                             f"<i>Log into TextVerified, buy the line manually, and assign it to this user!</i>",
                        parse_mode="HTML",
                        reply_markup=kb
                    )
                except Exception as e:
                    logger.error(f"Failed to alert admin {admin_id}: {e}")
                    await notify_admin(f"couldnt alert admin: {e}")
                    
            
        context.user_data.pop("otp_step", None)
        return
        
    # 4. 🚀 THE API PURCHASE (For 1-30 Day standard numbers)
    try:
        phone_number, rental_id, error_msg = await fetch_rental_number_from_textverified(
            service_name=service,
            state=state,
            duration_api=duration_api,
            always_on=always_on,
            is_renewable=is_renewable
        )

        # If the API function returned a specific error message, raise it!
        if error_msg:
            raise ValueError(error_msg)

        # If it returned blank, trigger the default stock error
        if not phone_number or not rental_id:
            raise ValueError("The provider is temporarily out of stock for this specific service or state.")

        # 5. 💾 SAVE TO DATABASE
        days_map = {
            "ONE_DAY": 1, "THREE_DAY": 3, "SEVEN_DAY": 7, "FOURTEEN_DAY": 14, 
            "THIRTY_DAY": 30, "ONE_MONTH": 30, "TWO_MONTHS": 60, "THREE_MONTHS": 90, 
            "SIX_MONTHS": 180, "NINE_MONTHS": 270, "ONE_YEAR": 365,
            "FOREVER": 36500
        }
        days_to_expire = days_map.get(duration_api, 1)

        save_active_rental(
            user_id=user_id,
            rental_id=rental_id,
            phone_number=phone_number,
            service_name=service,
            always_on=always_on,
            is_renewable=is_renewable,
            days_to_expire=days_to_expire
        )

        # 6. 🎉 DELIVER TO THE USER
        try:
            await processing_msg.delete()
        except Exception:
            pass
            
        set_delivery_status(order_id, "delivered")
        success_message = f"""
✅ <b>Rental Successful!</b>

📱 <b>Number:</b> <code>{phone_number}</code>
💬 <b>Service:</b> {service.capitalize()}
⏱️ <b>Duration:</b> {days_to_expire} Days

💵 Your wallet was successfully charged <b>${price:.2f}</b>.
<i>You can manage your rental in the 'My Numbers' menu.</i>
"""

        # 🔘 ADD THE BUTTON TO JUMP STRAIGHT TO THEIR NUMBERS
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📱 Manage My Numbers", callback_data="my_rentals_back")]])
        await safe_send(update, context, success_message, parse_mode="HTML")
   
        # ⏰ SET THE EXACT ALARMS!
        delay_seconds = days_to_expire * 24 * 3600
        reminder_seconds = delay_seconds - (6 * 3600) # 6 hours before expiration!
        
        if context.job_queue:
            # Alarm 1: The 6-Hour Warning
            if reminder_seconds > 0:
                context.job_queue.run_once(
                    scheduled_6h_reminder,
                    when=reminder_seconds,
                    data={"rental_id": rental_id, "user_id": user_id},
                    name=f"warn_{rental_id}"
                )
                
            # Alarm 2: The Kill Switch
            context.job_queue.run_once(
                scheduled_expire_rental,
                when=delay_seconds,
                data={"rental_id": rental_id, "user_id": user_id},
                name=f"expire_{rental_id}"
            )
            
            # 🤖 ALARM 3: THE SECRET AUTO-EXTENDER (For 2 Months)
            if duration_api == "TWO_MONTHS":
                day_29_seconds = 29 * 24 * 3600 # Wakes up exactly in 29 days
                context.job_queue.run_once(
                    scheduled_auto_extend,
                    when=day_29_seconds,
                    data={"rental_id": rental_id},
                    name=f"auto_extend_{rental_id}"
                )
                
        # Wipe the memory only AFTER all alarms are successfully set
        context.user_data.pop("otp_step", None)

    except Exception as e:
        logger.error(f"Rental Purchase Failed: {e}")
        await notify_admin(f"Rental Purchase Failed: {e}")
        
        # 7. 🛟 THE AUTO-REFUND (Safety Net)
        add_user_balance_usd(user_id, price)
        set_order_status(order_id, "cancelled")
        
        # 🛡️ SAFE DELETE
        try:
            await processing_msg.delete()
        except Exception:
            pass
            
        await safe_send(
            update,
            context,
            f"❌ Purchase failed. Contact Support\n\n"
            f"💰 <b>Your ${price:.2f} has been instantly refunded to your wallet.</b>\n\n",
            parse_mode="HTML"
        )
        context.user_data.pop("otp_step", None)


# Function to send the service list with the buttons
async def send_service_list_with_buttons(update, context):
    try:
        logger.info("Sending service list to user.")
        
        # Fetch the service list and send the .txt file using your existing function
        await send_services_txt(update, context, capability="sms", is_rental=True)

        # Create the buttons for the user to choose
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, I have the Product ID", callback_data="otp_rental_product_id"),
                InlineKeyboardButton("🌐 Universal", callback_data="otp_rental_universal")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_send(update, context, "Select your option:", reply_markup=reply_markup)
        
        # 👇 ADD THIS ONE LINE 👇
        context.user_data["otp_step"] = "awaiting_rental_button" 
        
        logger.info("Service list and buttons sent successfully.")

    except Exception as e:
        logger.error(f"Error sending service list with buttons: {e}")
        await notify_admin(f"Error sending service list with buttons: {e}")
        if update.callback_query:
            await safe_send(update, context, "An error occurred while fetching the service list.")
            

async def resend_rental_menu(update, context):
    """Silently pushes the rental buttons back to the user if they type text."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes, I have the Product ID", callback_data="otp_rental_product_id"),
            InlineKeyboardButton("🌐 Universal", callback_data="otp_rental_universal")
        ]
    ]
    await safe_send(
        update,
        context,
        " <b>Please click an option below:</b>", 
        reply_markup=InlineKeyboardMarkup(keyboard), 
        parse_mode="HTML"
    )            
            
async def handle_rental_universal(update: Update, context: CallbackContext):
    """
    Handles the 'Universal' button click. Blocks 1-day universal rentals and forwards to state selection.
    """
    q = update.callback_query
    await q.answer()

   # 🛑 THE 1-DAY UNIVERSAL BLOCKER (The Correct Way!) 🛑
    duration_api = context.user_data.get("otp_duration_api", "ONE_DAY")
    if duration_api == "ONE_DAY":
        msg = (
            "⚠️ <b>Minimum Duration Required</b>\n\n"
            "Premium Universal (All-Services) numbers require a minimum rental period of <b>3 Days</b>. "
            "The provider does not offer 1-Day leases for this specific line.\n\n"
            "<i>Please restart and select a longer duration, or choose a specific service (like WhatsApp or Telegram) for a 1-Day rental.</i>"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🗑️ Close & Restart", callback_data="close_menu")]])
        
        try:
            await safe_send(update, context, msg, parse_mode="HTML", reply_markup=kb)
        except Exception:
            await safe_send(update, context,msg, parse_mode="HTML", reply_markup=kb)
        
        context.user_data.pop("otp_step", None)
        return
    

    # 2. Inject the ID into memory
    context.user_data["otp_service_name"] = "allservices"
    
    # 3. Call your state function (Assuming it's in the same rental.py file)
    return await ask_state_or_random(update, context)          


# Function to reserve rental number and handle the wake request
async def fetch_rental_number_from_textverified(service_name: str, state: str, duration_api: str, always_on: bool, is_renewable: bool):
    client, reservations, wake_requests, sms_client, NumberType, ReservationCapability, RentalDuration = get_textverified_client()
    try:
        logger.info(f"🚀 User requested DB Name: '{service_name}' in {state}")
        
        # ✅ THE HYBRID CHECK
        if service_name and any(keyword in service_name.lower() for keyword in ["universal", "general", "not listed", "allservices", "servicenotlisted"]):
            api_service_name = "servicenotlisted"
            logger.info(" Bot spotted a Universal keyword. Overriding to 'allservices'.")
        else:
            api_service_name = service_name
            logger.info("✅ No Universal keywords found. Keeping original name.")

        logger.info(f"💵 SENDING TO TEXTVERIFIED BILLING: '{api_service_name}'")
                
        # --- THE API TRANSLATOR ---
        # --- THE API TRANSLATOR ---
        api_mapped_duration = "THIRTY_DAY" if duration_api in ["ONE_MONTH", "TWO_MONTHS"] else duration_api
            
        if duration_api == "TWO_MONTHS":
            is_renewable = True
        else:
            is_renewable = False

        # 👇 TextVerified blocks 'Always On' for short-term Universal lines!
        if api_service_name == "servicenotlisted":
            if api_mapped_duration in ["ONE_DAY", "THREE_DAY", "SEVEN_DAY", "FOURTEEN_DAY"]:
                always_on = False 

        # Build the perfectly clean payload!
        kwargs = {
            "service_name": api_service_name,
            "number_type": NumberType.MOBILE,
            "capability": ReservationCapability.SMS,
            "duration": getattr(RentalDuration, api_mapped_duration), 
            "always_on": always_on,  
            "is_renewable": is_renewable,
            "allow_back_order_reservations": False # 👈 WE MUST INCLUDE THIS!
        }
        
        if state and state.lower() != "random":
            acs = _area_codes_for_state(state)
            if acs:
                kwargs["area_code_select_option"] = acs[:15]
                
                
        
        # ---------------------------------------------------------
        # 🧪 THE GHOST INTERCEPTOR (TEST MODE)
        # ⚠️ Change to False when you are ready for real users!
        TEST_MODE = False
        
        if TEST_MODE:
            await asyncio.sleep(2)  # Simulate network delay
            logger.info("🧪 TEST MODE ACTIVE: Faking successful TextVerified response!")
            
            # We return a fake phone number, a fake rental ID, and No Errors!
            # Your bot will think it successfully bought the number and continue the flow.
            return "+15550009999", "ghost_rental_12345", None
        # ---------------------------------------------------------   

        # 1. Buy the number and get the "mini-receipt"
        reservation = await asyncio.to_thread(reservations.create, **kwargs)
        
        if hasattr(reservation, 'reservations') and len(reservation.reservations) > 0:
            mini_receipt = reservation.reservations[0]
        else:
            mini_receipt = reservation
            
        rental_id = getattr(mini_receipt, "id", None)
        
        if not rental_id:
            # FIXED: Returning 3 items to prevent Python crashing
            return None, None, "The provider failed to assign a Rental ID."

        # 2. ✅ THE FIX: Ask TextVerified for the FULL receipt using the ID
        logger.info(f"🔍 Fetching full details for Rental ID: {rental_id}")
        full_rental_obj = await asyncio.to_thread(reservations.details, rental_id)

        # 3. Safely extract the number from the FULL receipt
        if hasattr(full_rental_obj, "phone_number"):
            rental_number = full_rental_obj.phone_number
        elif hasattr(full_rental_obj, "target_number"):
            rental_number = full_rental_obj.target_number
        elif hasattr(full_rental_obj, "target"):
            rental_number = full_rental_obj.target
        elif hasattr(full_rental_obj, "line"):
            rental_number = full_rental_obj.line
        elif hasattr(full_rental_obj, "number"):
            rental_number = full_rental_obj.number
        else:
            available_props = [p for p in dir(full_rental_obj) if not p.startswith("_")]
            logger.error(f"❌ Hidden SDK Attributes on FULL object: {available_props}")
            # FIXED: Returning 3 items to prevent Python crashing
            return None, None, "The provider generated your number, but the bot couldn't read the format. Check console!"

        # ✅ SMART AUTO-WAKE LOGIC
        if not always_on:
            logger.info(f"⏰ Line is sleeping. Waking up Rental ID: {rental_id}")
            # We must pass the full object to the wake request
            await asyncio.to_thread(wake_requests.create, full_rental_obj)
        else:
            logger.info(f"⚡ Line is Always On. Skipping wake request for Rental ID: {rental_id}")

        return rental_number, rental_id, None

    except Exception as e:
        error_msg = str(e)
        logger.error(f"💥 TextVerified Rental Error: {error_msg}")
        await notify_admin(f"TextVerified Rental Error{e}")
        
        if "Invalid service name" in error_msg:
            # FIXED: Returning 3 items
            return None, None, "This specific service is not available for Long-Term Rentals. Please try a different service."
        elif "balance" in error_msg.lower():
            return None, None, "Purchasing Error Please Try Again Or Contact Support."
        else:
            return None, None, "The provider could not fulfill this request at this time Please Contact Support."
        
        

async def my_rentals_menu(update, context):
    """Displays a list of the user's active rental numbers."""
    
    # 🧹 THE SWEEP: Clean up the entire database before loading the list!
    auto_expire_rentals()
    user_id = update.effective_user.id
    query = update.callback_query

    # 1. Fetch their active numbers using the clean DB function
    rentals = get_user_active_rentals(user_id)

    # 2. If they have no active numbers, tell them cleanly
    if not rentals:
        empty_text = "📭 You don't have any active rental numbers right now."
        if query:
            await safe_send(update, context, empty_text)
        else:
            await safe_send(update, context, empty_text)
        return

    # 3. Build the dynamic inline keyboard
    keyboard = []
    for rental_id, phone, service in rentals:
        # Formats the button: "🟢 Whatsapp - 9209147003"
        button_text = f"🟢 {service.capitalize()} - {phone}"
        
        # We attach the specific TextVerified rental_id directly to the button
        callback_data = f"manage_rental:{rental_id}" 
        
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    menu_text = "📱 **Your Active Rentals:**\n\nClick a number below to manage it or check for new SMS:"
    
    # 4. Send the menu
    if query:
        await safe_send(update, context, menu_text, parse_mode="Markdown", reply_markup=reply_markup)      

    else:
        await safe_send(update, context, menu_text, parse_mode="Markdown", reply_markup=reply_markup)      
        
        
async def manage_rental_menu(update, context):
    
    # 🧹 THE SWEEP: Clean up the entire database before loading the list!
    
    """Displays the management screen with a live expiration countdown and accurate status."""
    query = update.callback_query
    await query.answer() 
    
    # 1. Extract the rental_id
    rental_id = query.data.split(":")[1]
    
    # 2. Fetch details
    details = get_rental_details(rental_id)
    if not details:
        await safe_send(update, context,"❌ This rental is no longer active or could not be found.")
        return
        
    phone, service, always_on, expiration_time = details
    
    # 3. Calculate the exact time remaining
    now = datetime.datetime.now(datetime.timezone.utc)
    time_left = expiration_time - now
    
    # Check if it is expired
    is_expired = time_left.total_seconds() <= 0
    
    if not is_expired:
        days = time_left.days
        hours, remainder = divmod(time_left.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        # Format it cleanly based on how much time is left
        if days > 0:
            countdown_str = f"{days} days, {hours} hours, {minutes} mins"
        else:
            countdown_str = f"{hours} hours, {minutes} mins, {seconds} seconds"
            
        status_text = "🟢 Active"
        footer_text = "Click the button below to connect to the network and fetch your messages."
    else:
        countdown_str = "0 hours, 0 mins (Expired)"
        status_text = "🔴 Expired"
        footer_text = "This number has expired and can no longer receive messages."
    
    # 4. Build the Keyboard (Hide Check SMS if expired)
    keyboard = []
    if not is_expired:
        keyboard.append([
            InlineKeyboardButton("📥 Check SMS", callback_data=f"check_sms:{rental_id}"),
            InlineKeyboardButton("⏳ Extend Rental", callback_data=f"extend_rental:{rental_id}")
        ])
        
    else:
        mark_rental_expired(rental_id)    
        
    keyboard.append([InlineKeyboardButton("🔙 Back to List", callback_data="my_rentals_back")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # 5. Show the beautiful UI (Using pure HTML tags to fix the asterisk glitch)
    menu_text = (
        f"📱 <b>Number Details</b>\n\n"
        f"<b>Number:</b> <code>{phone}</code>\n\n"
        f"<b>Service:</b> {service.capitalize()}\n\n"
        f"<b>Status:</b> {status_text}\n\n"
        f"<b>ID:</b> <code>{rental_id}</code>\n\n"
        f"<b>⚠️ Please note this number will expire in - {countdown_str}</b>\n\n"
        f"<i>{footer_text}</i>"
    )
    

    await safe_send(update, context, menu_text, parse_mode="HTML", reply_markup=reply_markup)
        

async def check_sms_action(update, context):
    """The smart engine that pulls SMS history and sorts by time."""
    query = update.callback_query
    await query.answer()
    
    rental_id = query.data.split(":")[1]
    await safe_send(update, context,"⏳ Connecting to Magic Bot and checking inbox... please wait.")

    details = get_rental_details(rental_id)
    if not details:
        await safe_send(update, context, "❌ This rental is no longer active.")
        return

    phone, service, always_on, expiration_time = details

    try:
        # 1. Connect to API
        client, reservations, wake_requests, sms_client, NumberType, ReservationCapability, RentalDuration = get_textverified_client()
        
        # 2. Fetch the current rental object
        rental_obj = await asyncio.to_thread(reservations.details, rental_id)
        # 🛑 DROP THIS X-RAY PRINT RIGHT HERE 🛑
        print(f"🕵️ X-RAY RENTAL OBJ: {[p for p in dir(rental_obj) if not p.startswith('_')]}")
        if hasattr(rental_obj, '__dict__'):
            print(f"🕵️ X-RAY DICT: {rental_obj.__dict__.keys()}")

        # 3. Smart Wake for sleeping lines
        if not always_on and getattr(rental_obj, 'status', '').lower() == 'sleeping':
            await safe_send(update, context, "⏰ Line is sleeping. Sending Wake command... (Takes ~3 seconds)")
            await asyncio.to_thread(wake_requests.create, rental_obj)
            await asyncio.sleep(3)
            rental_obj = await asyncio.to_thread(reservations.details, rental_id) 

        # 4. 📥 THE MASTER FETCH (Deep Scan)
        raw_messages = []
        try:
            # Fetch the global SMS inbox
            history = await asyncio.to_thread(sms_client.list)
            all_msgs = list(getattr(history, 'data', history)) if history else []
            
            # 🛑 X-RAY THE INBOX 🛑
            print(f"🕵️ X-RAY INBOX: Found {len(all_msgs)} total messages in your account.")
            if all_msgs:
                # Print the exact dictionary of the very first message so we can see the secret variable names
                first_msg_dict = all_msgs[0].__dict__ if hasattr(all_msgs[0], '__dict__') else str(all_msgs[0])
                print(f"🕵️ X-RAY FIRST MSG: {first_msg_dict}")

            # The Brute-Force Filter
            # Instead of guessing the variable name, we turn the entire message into a string
            # and search for the last 10 digits of your phone number anywhere inside it!
            phone_str = str(phone)[-10:] 
            
            for m in all_msgs:
                msg_data = str(m.__dict__ if hasattr(m, '__dict__') else m)
                if phone_str in msg_data:
                    raw_messages.append(m)
                    print(f"✅ Found a match for {phone_str}!")
                        
        except Exception as e:
            print(f"Failed to fetch history: {e}")
            await notify_admin(f"TextVerified Rental Error{e}")

        # 5. ⏱️ THE TIME SORTER
        recent_msgs = []
        history_msgs = []
        now = datetime.datetime.now(datetime.timezone.utc)
        
        # Capitalize the service name (e.g., "whatsapp" becomes "Whatsapp")
        svc_name = service.capitalize()

        for msg in raw_messages:
            # 1. 🧹 THE SMART EXTRACTOR
            parsed = getattr(msg, 'parsed_code', None)
            raw_text = getattr(msg, 'sms_content', getattr(msg, 'text', str(msg)))
            
            # Split the raw text to separate the code from the warnings and garbage hashes
            lines = raw_text.replace('<#>', '').strip().split('\n')
            
            # If TextVerified already parsed it, use that. Otherwise, use the first line.
            code_to_show = parsed if parsed else lines[0].strip()
            
            # Grab the second line (the warning message) if it exists, ignoring the hash at the end!
            extra_text = lines[1].strip() if len(lines) > 1 else ""
            
            # Escape HTML to prevent Telegram crashes
            safe_code = html.escape(code_to_show)
            safe_extra = f"{html.escape(extra_text)} " if extra_text else ""

            # Safely extract and parse the API timestamp
            msg_time = None
            for attr in ['created_at', 'date_received', 'timestamp', 'date']:
                val = getattr(msg, attr, None)
                if val:
                    if isinstance(val, str):
                        try:
                            msg_time = datetime.datetime.fromisoformat(val.replace('Z', '+00:00'))
                        except: pass
                    elif isinstance(val, datetime.datetime):
                        msg_time = val
                    break
            
            # Calculate Time
            age_mins = 0
            time_str = "Just now"
            if msg_time:
                if msg_time.tzinfo is None:
                    msg_time = msg_time.replace(tzinfo=datetime.timezone.utc)
                    
                diff = now - msg_time
                age_seconds = int(diff.total_seconds())
                age_mins = age_seconds // 60
                
                if age_seconds < 60:
                    time_str = f"{max(0, age_seconds)} seconds"
                elif age_mins < 60:
                    time_str = f"{age_mins} mins"
                elif age_mins < 1440:
                    hours = age_mins // 60
                    time_str = f"{hours} hour{'s' if hours > 1 else ''}"
                else:
                    days = age_mins // 1440
                    time_str = f"{days} day{'s' if days > 1 else ''}"

            # 🪣 DROP INTO THE CORRECT BUCKET
            if age_mins <= 5:
                # Bucket 1: Live Code! (Includes the warning text below it)
                formatted_msg = (
                    f"💬 <b>From {svc_name}:</b>\n"
                    f"<b>Your {svc_name} code is <code>{safe_code}</code></b>\n"
                    f"{safe_extra}({time_str} ago)"
                )
                recent_msgs.append(formatted_msg)
            elif age_mins <= 30:
                # Bucket 2: Recent History (Clean, no warning text)
                formatted_msg = (
                    f"💬 <b>From {svc_name}:</b>\n"
                    f"<b>Your {svc_name} code is <code>{safe_code}</code></b>\n"
                    f"({time_str} ago)"
                )
                history_msgs.append(formatted_msg)
            else:
                # Bucket 3: The "Old Faithful" (Over 30 mins, Clean inline format)
                formatted_msg = (
                    f"💬 <b>From {svc_name}:</b>\n"
                    f"<i>Last received</i> <b>Your {svc_name} code is <code>{safe_code}</code></b> <i>over {time_str} ago</i>"
                )
                history_msgs.append(formatted_msg)

        # 6. 🏗️ THE UI BUILDER (Decision Tree)
        if not recent_msgs and not history_msgs:
            # Scenario: Brand New Line
            text = f"📭 <b>Inbox for {phone}:</b>\n\nNo messages yet. If you just requested the code on {svc_name}, wait 10 seconds and click Check Again."
        else:
            # Scenario: Build the Trust UI (WITH THE ARROWS!)
            text = f"📱 <b>Inbox for {phone}:</b>\n\n"
            
            text += "🟢 <b>NEW (Last 5 Mins):</b> ⤵\n"
            if recent_msgs:
                text += "\n\n".join(recent_msgs) + "\n\n"
            else:
                text += f"📭 <i>No new messages yet. If you just requested the code, wait 10 seconds and click Check Again.</i>\n\n"
            
            text += "⏳ <b>HISTORY:</b> ⤵\n"
            if history_msgs:
                # Shows ONLY the absolute most recent historical message
                text += "\n\n".join(history_msgs[:1])
            else:
                text += "<i>No older history for this line.</i>"

        # 7. Build Keyboard & Send
        keyboard = [
            [InlineKeyboardButton("🔄 Check Again", callback_data=f"check_sms:{rental_id}")],
            [InlineKeyboardButton("🔙 Back to Number", callback_data=f"manage_rental:{rental_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await safe_send(update, context, text, parse_mode="HTML", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error  {e}")
        await notify_admin(f"Checking Error Please contact Support{e}")
        await safe_send(update, context, f"💥 Checking Error Please contact Support.")
        
        
        
async def trigger_extension_menu(update, context):
    """Triggered when the user clicks '➕ Extend Rental' on a specific number."""
    query = update.callback_query
    await query.answer()
    
    # Extract the rental_id they clicked
    rental_id = query.data.split(":")[1]
    details = get_rental_details(rental_id)
    if not details:
        await safe_send(update, context, "❌ This rental is no longer active or could not be found.")
        return
        
    phone, service, always_on, expiration_time = details
    
    # 2. 🛑 The 1-Day Blocker
    # If your DB tracks the original duration, check it here. 
    # (Assuming you added a way to check if it was a ONE_DAY line)
    # If you don't track original duration in DB yet, we can skip this or add it to DB later.
    
    # 3. Save the critical data to memory for the next step
    context.user_data["extending_rental_id"] = rental_id
    context.user_data["extending_service"] = service
    context.user_data["extending_phone"] = phone
    
    # 4. Generate the proper prices based on service type
    prices = RENEWAL_UNIVERSAL_PRICES if service.lower() == "allservices" else RENEWAL_BASE_PRICES

    # 5. Build the beautiful Text Menu (Safely!)
    menu_text = (
        f"📈 <b>Extend Your Rental</b>\n"
        f"How long would you like to extend <code>{phone}</code>?\n\n"
        f"<b>Standard Extensions:</b>\n"
    )
    
    # Only show the 1-Day option if it's NOT a Universal line!
    if "ONE_DAY" in prices:
        menu_text += f"<b>A.</b> 1 Day - <b>${prices['ONE_DAY']:.2f}</b>\n"
        
    menu_text += (
        f"<b>B.</b> 3 Days - <b>${prices.get('THREE_DAY', 0.0):.2f}</b>\n"
        f"<b>C.</b> 7 Days - <b>${prices.get('SEVEN_DAY', 0.0):.2f}</b>\n"
        f"<b>D.</b> 14 Days - <b>${prices.get('FOURTEEN_DAY', 0.0):.2f}</b>\n"
        f"<b>E.</b> 1 Month - <b>${prices.get('THIRTY_DAY', 0.0):.2f}</b>\n"
        f"<b>F.</b> 2 Months - <b>${prices.get('TWO_MONTHS', 0.0):.2f}</b>\n\n"
        f"<b>Premium Long-Term:</b>\n"
        f"<b>G.</b> 3 Months - <b>${prices.get('THREE_MONTHS', 0.0):.2f}</b>\n"
        f"<b>H.</b> 6 Months - <b>${prices.get('SIX_MONTHS', 0.0):.2f}</b>\n"
        f"<b>I.</b> 9 Months - <b>${prices.get('NINE_MONTHS', 0.0):.2f}</b>\n"
        f"<b>J.</b> 1 Year - <b>${prices.get('ONE_YEAR', 0.0):.2f}</b>\n"
        f"<b>K.</b> Forever - <b>${prices.get('FOREVER', 0.0):.2f}</b>\n\n"
        f"<i>Type the letter of your choice below to secure your line, Example B for 3 days or type 'cancel' to exit.</i>")
    
    # We set a flag so the bot knows it is actively listening for an A-J response
    context.user_data["awaiting_extension_choice"] = True
    
    await safe_send(update, context,menu_text, parse_mode="HTML")
    
    
    
    
async def handle_extension_text(update, context):
    """Listens for the A-K response when extending a rental."""
    # 1. If we aren't waiting for an extension choice, ignore their message!
    if not context.user_data.get("awaiting_extension_choice"):
        return 
        
    text = update.message.text.lower().strip()
    user_id = update.effective_user.id
    
    # 2. The Cancel Switch
    if text == 'cancel':
        context.user_data.pop("awaiting_extension_choice", None)
        await safe_send(update, context, "🛑 <b>Extension cancelled.</b>", parse_mode="HTML")
        return

    # 3. The Letter Mapper (Translates A-J into API Strings and Days)
    extension_map = {
        'a': ('ONE_DAY', 1),
        'b': ('THREE_DAY', 3),
        'c': ('SEVEN_DAY', 7),
        'd': ('FOURTEEN_DAY', 14),
        'e': ('THIRTY_DAY', 30),
        'f': ('TWO_MONTHS', 60), 
        'g': ('THREE_MONTHS', 90),
        'h': ('SIX_MONTHS', 180),
        'i': ('NINE_MONTHS', 270),
        'j': ('ONE_YEAR', 365),
        'k': ('FOREVER', 36500)
    }

    if text not in extension_map:
        await safe_send(update, context, "⚠️ <b>Invalid choice.</b> Please reply with a single letter (A - J) or type 'cancel'.", parse_mode="HTML")
        return

    api_duration, days_to_add = extension_map[text]
    rental_id = context.user_data.get("extending_rental_id")
    service = context.user_data.get("extending_service")
    phone = context.user_data.get("extending_phone")
    
    # 4. Calculate the Exact Price
    prices = RENEWAL_UNIVERSAL_PRICES if service.lower() == "allservices" else RENEWAL_BASE_PRICES
    
    # We mapped 'E' to 'TWO_MONTHS', so prices['TWO_MONTHS'] perfectly grabs the $55.00
    price_to_charge = prices.get(api_duration) 

    # 5. 🛡️ THE ESCROW HOLD (Wallet Deduction)
    
    if not try_debit_user_balance_usd(user_id, price_to_charge):
        # They are broke! Show the top-up message.
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("💳 Top up wallet", callback_data="add_funds")]])
        await safe_send(
            update,
            context,
            f"❌ <b>Insufficient balance.</b>\n\n"
            f"Extension cost: <b>${price_to_charge:.2f}</b>\n"
            f"Please top up your wallet to extend this line.",
            parse_mode="HTML",
            reply_markup=kb
        )
        # We clear the flag so they aren't stuck in a loop
        context.user_data.pop("awaiting_extension_choice", None)
        return

    # 6. Show the "Wizard of Oz" Loading Message
    processing_msg = await safe_send(update, context,"🔄 <i>Syncing your extended line with the network...</i>", parse_mode="HTML")

    # 7. ROUTE A: Standard Automated Extension (A - E)
    if text in ['a', 'b', 'c', 'd', 'e']:
        client, reservations, _, _, _, _, RentalDuration = get_textverified_client()
        
        # We cap the API request to 30 days so the SDK doesn't crash
        api_mapped = "THIRTY_DAY" if api_duration == "TWO_MONTHS" else api_duration
        
        
        
        try:
            # Ping the SDK to extend it using the correct method and kwargs!
                        
            await asyncio.to_thread(
                reservations.extend_nonrenewable, 
                rental_id=rental_id, 
                extension_duration=getattr(RentalDuration, api_mapped)
                
            )
            
            
        except Exception as e:
            logging.error(f"🚨 TEXTVERIFIED EXTENSION FAILED for {rental_id}: {e}")
            await notify_admin(f"EXTENSION FAILED for {rental_id}: {e}")
            
            # 🚨 THE AUTO-REFUND IF NETWORK FAILS
            add_user_balance_usd(user_id, price_to_charge)
            await processing_msg.edit_text(f"❌ <b>Network Error:</b> The provider locked this line... Your <b>${price_to_charge:.2f}</b> has been refunded.", parse_mode="HTML")
            context.user_data.pop("awaiting_extension_choice", None)
            return

    # 8. ROUTE B: The Premium Concierge (F - J)
    else:
        # We successfully faked it! Alert ALL admins in the background.
        if ADMIN_IDS:
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=f"🚨 <b>MANUAL RENEWAL ORDER!</b>\n\n"
                             f"User: <code>{user_id}</code>\n"
                             f"Line: <code>{phone}</code> ({service})\n"
                             f"Duration: {api_duration} ({days_to_add} Days)\n"
                             f"Paid: ${price_to_charge:.2f}\n\n"
                             f"<i>Log into TextVerified and manually extend this specific line to prevent expiration!</i>",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
    # 9. 💾 UPDATE THE DATABASE & RESET REMINDERS
    # 9. 💾 UPDATE THE DATABASE & RESET REMINDERS
    try:
        # 1. Update PostgreSQL
        extend_rental_timer(rental_id, days_to_add)
        
        # 2. Reset the Bot's Internal Alarm Clock!
        if context.job_queue:
            # Delete old Kill Switch
            old_expire_jobs = context.job_queue.get_jobs_by_name(f"expire_{rental_id}")
            for job in old_expire_jobs:
                job.schedule_removal()
                
            # Delete old 6-Hour Warning
            old_warn_jobs = context.job_queue.get_jobs_by_name(f"warn_{rental_id}")
            for job in old_warn_jobs:
                job.schedule_removal()
                
            # Grab the brand new expiration date we just saved to the DB
            details = get_rental_details(rental_id)
            if details:
                new_exp = details[3]
                now = datetime.datetime.now(datetime.timezone.utc)
                
                delay_seconds = (new_exp - now).total_seconds()
                reminder_seconds = delay_seconds - (6 * 3600) # 6 hours before expiration
                
                # SET ALARM 1: The 6-Hour Warning
                if reminder_seconds > 0:
                    context.job_queue.run_once(
                        scheduled_6h_reminder,
                        when=reminder_seconds,
                        data={"rental_id": rental_id, "user_id": user_id},
                        name=f"warn_{rental_id}"
                    )
                    
                # SET ALARM 2: The Kill Switch
                if delay_seconds > 0:
                    context.job_queue.run_once(
                        scheduled_expire_rental,
                        when=delay_seconds,
                        data={"rental_id": rental_id, "user_id": user_id},
                        name=f"expire_{rental_id}"
                    )
                
    except Exception as e:
        logging.error(f"🚨 DB Update or Alarm reset failed: {e}")
        await notify_admin(f"Alarm reset failed: {e}")

        
        return      

    # 10. The Grand Finale
    await processing_msg.edit_text(
        f"✅ <b>Extension Successful!</b>\n\n"
        f"Line <code>{phone}</code> has been successfully secured for an additional <b>{days_to_add} Days</b>.\n"
        f"<b>${price_to_charge:.2f}</b> was deducted from your wallet.",
        parse_mode="HTML"
    )
    
    # Wipe the memory completely clean
    context.user_data.pop("awaiting_extension_choice", None)
    context.user_data.pop("extending_rental_id", None)
    context.user_data.pop("extending_service", None)
    context.user_data.pop("extending_phone", None)    
    
async def scheduled_6h_reminder(context: CallbackContext):
    """The 6-Hour warning alarm goes off! DM the user to extend their number."""
    job_data = context.job.data
    rental_id = job_data["rental_id"]
    user_id = job_data.get("user_id")

    # 1. Double check the number is still active
    details = get_rental_details(rental_id)
    if not details:
        return
        
    phone_number = details[0]
    service = details[1]

    # 2. Fire the warning DM!
    if user_id:
        try:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("⏳ Extend Rental Now", callback_data=f"extend_rental:{rental_id}")]])
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"⚠️ <b>Rental Expiring Soon!</b>\n\n"
                    f"Your premium line <code>{phone_number}</code> ({service.capitalize()}) will expire in exactly <b>6 Hours</b>.\n\n"
                    f"<i>If you do not extend it, the number will be deleted and cannot be recovered.</i> \n\n"
                    f"🛠 <b>Need help? Contact {SUPPORT_HANDLE}</b>"
                ),
                parse_mode="HTML",
                reply_markup=kb
            )
        except Exception:
            pass # Fails silently if they blocked the bot    
    
async def scheduled_expire_rental(context: CallbackContext):
    """The exact alarm goes off! Mark the specific rental as expired and DM the user."""
    job_data = context.job.data
    rental_id = job_data["rental_id"]
    user_id = job_data.get("user_id")

    # 1. Grab the phone number from the DB before we expire it
    details = get_rental_details(rental_id)
    
    # If it finds the details, grab the phone number (index 0). Otherwise fallback.
    phone_number = details[0] if details else rental_id

    # 2. Update the database instantly
    mark_rental_expired(rental_id)

    # 3. Tell the user it expired!
    if user_id:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"🔴 <b>Rental Expired</b>\n\nYour premium line (<code>{phone_number}</code>) has run out of time and was removed from your active list. \n\n"
                    f"🛠 <b>Need help? Contact {SUPPORT_HANDLE}</b>"
                ),
                parse_mode="HTML"
            )
        except Exception:
            pass # Fails silently if they blocked the bot  
        
        
async def scheduled_auto_extend(context: CallbackContext):
    """Wakes up on Day 29 to silently pay TextVerified for the 2nd month of a 60-day rental."""
    job_data = context.job.data
    rental_id = job_data["rental_id"]

    try:
        # 1. Connect to TextVerified
        client, reservations, _, _, _, _, RentalDuration = get_textverified_client()
        
        # 2. Tell TextVerified to add exactly 30 more days to the line
        await asyncio.to_thread(
            reservations.extend_nonrenewable, 
            rental_id=rental_id, 
            extension_duration=getattr(RentalDuration, "THIRTY_DAY")
        )
        
        logger.info(f"✅ AUTO-EXTEND SUCCESS: Secretly bought Month 2 for Rental {rental_id}")

    except Exception as e:
        logger.error(f"🚨 AUTO-EXTEND FAILED: {e}")
        # 3. 🛟 The Failsafe! If TextVerified crashes on Day 29, it snipes your phone so you can save the number manually!
        await notify_admin(
            f"🚨 <b>URGENT AUTO-EXTEND FAILURE!</b>\n\n"
            f"Rental ID: <code>{rental_id}</code>\n"
            f"Error: {e}\n\n"
            f"<i>The bot tried to buy the 2nd month but failed. Please log into TextVerified and extend it manually before it expires tomorrow!</i>"
        )        