import datetime
import os
import os
import re
import asyncio
from telegram import Update
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext
from handlers.otp_handler import send_services_txt, _area_codes_for_state
from utils.validator import US_STATE_NAMES,suggest_us_states_full_name
import random
import requests
import httpx
import time
from utils.auto_delete import safe_send
from utils.textverified_client import get_textverified_client
from utils.db import get_rental_service_name_by_code,save_active_rental,get_user_active_rentals,get_rental_details
from telegram.constants import ParseMode
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
        await update.callback_query.message.reply_text(
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
            await update.message.reply_text("❌ Invalid Product ID. Please check the Rental Services list.")
            return

        # Validate the Product ID
        if len(product_id) in [3,4] and product_id.isdigit():
            context.user_data["otp_service_name"] = service_name
            context.user_data["otp_rental_product_id"] = product_id  # Store the rental product ID
            context.user_data["otp_step"] = "awaiting_rental_state"  # Next step: ask for the state
            
             # Ask the user if they want to select a state or not
            await ask_state_or_random(update, context)  # Call this function to ask the user for state or random selection
            
        else:
            # If the Product ID is invalid
            await update.message.reply_text("❌ Invalid Product ID. Please reply with a valid 4-digit Product ID (e.g. 0123).")


async def ask_state_or_random(update: Update, context: CallbackContext):
    """
    Ask the user if they want the number generated from a specific US state.
    """
    context.user_data["otp_step"] = "awaiting_state_or_random"
    
    # Send the prompt asking if the user wants the number from a specific state or random
    await update.message.reply_text(
        "Do you want the number to be generated from a specific US state?\n\n"
        "✅ Reply with: yes or no"
    )
    
    
    
async def handle_state_or_random(update: Update, context: CallbackContext):
    """
    Handle the user's response for state or random selection.
    """
    response = update.message.text.strip().lower()

    if response == "yes":
        # If user wants to specify the state
        context.user_data["otp_step"] = "awaiting_state"
        await update.message.reply_text(
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
        await update.message.reply_text("❌ Please reply with either 'yes' or 'no' to confirm.")   

                        
            
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
        
        await update.message.reply_text("❌ Invalid state. Please provide a valid state (e.g., California).")

        # If invalid, suggest valid states
        suggestions = suggest_us_states_full_name(state)
        suggestion_text = "Did you mean:\n" + "\n".join(suggestions) if suggestions else "❌ Invalid state. Please provide a valid state (e.g., California)."
        await update.message.reply_text(suggestion_text)


    
async def final_confirmation(update: Update, context: CallbackContext):
    """
    Display the final confirmation with the selected service, state, and price.
    """
    service = context.user_data.get("otp_service_name", "Unknown Service")
    state = context.user_data.get("otp_state", "Random")
    price = 3.00  # You can adjust this as per your service's pricing.

    confirmation_message = f"""
    FINAL CONFIRMATION:

    Service: {service}
    State: {state}
    Price: ${price}

    ⚠️ Please reply with either 'yes' or 'no' to confirm.
    """

    await update.message.reply_text(confirmation_message)
    # Handle user response for confirmation
    context.user_data["otp_step"] = "rental_final_confirm"  
    
    
async def confirm_rental(update: Update, context: CallbackContext):
    """
    Final confirmation for rental flow.
    """
    text = update.message.text.strip().lower()

    if text == "yes":
        # 1. 🛑 STRICT VALIDATION: If the bot forgot the critical data, ABORT!
        if "otp_service_name" not in context.user_data or "otp_duration_api" not in context.user_data:
            await update.message.reply_text("❌ Your session expired or the data was lost. Please restart your purchase.")
            context.user_data.pop("otp_step", None)
            return

        # 2. Grab the exact choices (No guessing allowed)
        service = context.user_data["otp_service_name"]
        duration_api = context.user_data["otp_duration_api"]
        
        # We can safely default these because they don't change the price
        state = context.user_data.get("otp_state", "Random")
        always_on = context.user_data.get("otp_always_on", True)
        is_renewable = context.user_data.get("otp_is_renewable", False)
        
        await update.message.reply_text("⏳ Requesting your rental line from the provider... please wait.")
                
        # The REAL API call (Training wheels are off!)
        rental_number, rental_id, error_msg = await fetch_rental_number_from_textverified(
            service, state, duration_api, always_on, is_renewable
        )
        
            
        if rental_number and rental_id:
            # 2. ✅ Convert the API duration string into an actual number of days
            days_to_expire = 1
            if duration_api == "THREE_DAY": days_to_expire = 3
            elif duration_api == "SEVEN_DAY": days_to_expire = 7
            elif duration_api == "FOURTEEN_DAY": days_to_expire = 14
            elif duration_api == "THIRTY_DAY": days_to_expire = 30
            
            # Grab the user's Telegram ID
            user_id = update.effective_user.id
            
            # 3. ✅ Lock it into the PostgreSQL Database (Synchronous call!)
            save_active_rental(
                user_id=user_id,
                rental_id=rental_id,
                phone_number=rental_number,
                service_name=service,
                always_on=always_on,
                is_renewable=is_renewable,
                days_to_expire=days_to_expire
            )
            
            await update.message.reply_text(f"✅ Reserved number!\n\nRental Number: {rental_number}\nService: {service}\nState: {state}")
            context.user_data.pop("otp_step", None)
            
        else:
            await update.message.reply_text(f"❌ Failed to fetch rental number:\n\n{error_msg}")
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

        logger.info("Service list and buttons sent successfully.")

    except Exception as e:
        logger.error(f"Error sending service list with buttons: {e}")
        if update.callback_query:
            await update.callback_query.message.reply_text("An error occurred while fetching the service list.")


# Function to reserve rental number and handle the wake request
async def fetch_rental_number_from_textverified(service_name: str, state: str, duration_api: str, always_on: bool, is_renewable: bool):
    client, reservations, wake_requests, sms_client, NumberType, ReservationCapability, RentalDuration = get_textverified_client()
    try:
        logger.info(f"🚀 User requested DB Name: '{service_name}' in {state}")
        
        # ✅ THE HYBRID CHECK
        if service_name and any(keyword in service_name.lower() for keyword in ["universal", "general", "not listed", "allservices"]):
            api_service_name = "allservices"
            logger.info("⚠️ Bot spotted a Universal keyword. Overriding to 'allservices'.")
        else:
            api_service_name = service_name
            logger.info("✅ No Universal keywords found. Keeping original name.")

        logger.info(f"💵 SENDING TO TEXTVERIFIED BILLING: '{api_service_name}'")
        
        kwargs = {
            "service_name": api_service_name,
            "number_type": NumberType.MOBILE,
            "capability": ReservationCapability.SMS,
            "duration": getattr(RentalDuration, duration_api), 
            "always_on": always_on,  
            "is_renewable": is_renewable,
            "allow_back_order_reservations": False
        }
        
        if state and state.lower() != "random":
            acs = _area_codes_for_state(state)
            if acs:
                kwargs["area_code_select_option"] = acs[:15]

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
        
        if "Invalid service name" in error_msg:
            # FIXED: Returning 3 items
            return None, None, "This specific service is not available for Long-Term Rentals. Please try a different service."
        elif "balance" in error_msg.lower():
            return None, None, "Our provider is currently out of balance. Please try again later."
        else:
            return None, None, "The provider could not fulfill this request at this time."
        
        

async def my_rentals_menu(update, context):
    """Displays a list of the user's active rental numbers."""
    user_id = update.effective_user.id
    query = update.callback_query

    # 1. Fetch their active numbers using the clean DB function
    rentals = get_user_active_rentals(user_id)

    # 2. If they have no active numbers, tell them cleanly
    if not rentals:
        empty_text = "📭 You don't have any active rental numbers right now."
        if query:
            await query.edit_message_text(empty_text)
        else:
            await update.message.reply_text(empty_text)
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
        await query.edit_message_text(menu_text, parse_mode="Markdown", reply_markup=reply_markup)
    else:
        await update.message.reply_text(menu_text, parse_mode="Markdown", reply_markup=reply_markup)      
        
        
async def manage_rental_menu(update, context):
    """Displays the management screen with a live expiration countdown."""
    query = update.callback_query
    await query.answer() 
    
    # 1. Extract the rental_id
    rental_id = query.data.split(":")[1]
    
    # 2. Fetch details
    details = get_rental_details(rental_id)
    if not details:
        await query.edit_message_text("❌ This rental is no longer active or could not be found.")
        return
        
    phone, service, always_on, expiration_time = details
    
    # 3. Calculate the exact time remaining
    # We use timezone.utc to perfectly match PostgreSQL's TIMESTAMP WITH TIME ZONE
    now = datetime.datetime.now(datetime.timezone.utc)
    time_left = expiration_time - now
    
    if time_left.total_seconds() > 0:
        days = time_left.days
        hours, remainder = divmod(time_left.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        # Format it cleanly based on how much time is left
        if days > 0:
            countdown_str = f"{days} days, {hours} hours, {minutes} mins"
        else:
            countdown_str = f"{hours} hours, {minutes} mins, {seconds} seconds"
    else:
        countdown_str = "0 hours, 0 mins (Expired)"
    
    # 4. Build the Keyboard
    keyboard = [
        [InlineKeyboardButton("📥 Check SMS", callback_data=f"check_sms:{rental_id}")],
        [InlineKeyboardButton("🔙 Back to List", callback_data="my_rentals_back")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # 5. Show the beautiful UI
    menu_text = (
        f"📱 **Number Details**\n\n"
        f"**Number:** `{phone}`\n\n"
        f"**Service:** {service.capitalize()}\n\n"
        f"**Status:** 🟢 Active\n\n"
        f"**ID:** `{rental_id}`\n\n"
        f"<b>⚠️ Please note this number will expire in - {countdown_str}</b>\n\n"
        f"Click the button below to connect to the network and fetch your messages."
    )
  

    await query.edit_message_text(menu_text, parse_mode="HTML", reply_markup=reply_markup)   
        

async def check_sms_action(update, context):
    """The smart engine that pulls SMS history and sorts by time."""
    query = update.callback_query
    await query.answer()
    
    rental_id = query.data.split(":")[1]
    await query.edit_message_text("⏳ Connecting to provider and checking inbox... please wait.")

    details = get_rental_details(rental_id)
    if not details:
        await query.edit_message_text("❌ This rental is no longer active.")
        return

    phone, service, always_on, expiration_time = details

    try:
        # 1. Connect to API
        client, reservations, wake_requests, sms_client, NumberType, ReservationCapability, RentalDuration = get_textverified_client()
        
        # 2. Fetch the current rental object
        rental_obj = await asyncio.to_thread(reservations.details, rental_id)

        # 3. Smart Wake for sleeping lines
        if not always_on and getattr(rental_obj, 'status', '').lower() == 'sleeping':
            await query.edit_message_text("⏰ Line is sleeping. Sending Wake command... (Takes ~3 seconds)")
            await asyncio.to_thread(wake_requests.create, rental_obj)
            await asyncio.sleep(3)
            rental_obj = await asyncio.to_thread(reservations.details, rental_id) 

        # 4. 📥 THE MASTER FETCH (Grab all history)
        raw_messages = []
        try:
            if hasattr(rental_obj, 'messages') and rental_obj.messages:
                raw_messages = list(rental_obj.messages)
            elif hasattr(sms_client, 'list'):
                history = await asyncio.to_thread(sms_client.list, reservation_id=rental_id)
                raw_messages = list(getattr(history, 'data', history)) if history else []
        except Exception as e:
            print(f"Failed to fetch history: {e}")

        # 5. ⏱️ THE TIME SORTER
        recent_msgs = []
        history_msgs = []
        now = datetime.datetime.now(datetime.timezone.utc)

        for msg in raw_messages:
            # Safely extract text and sender
            msg_text = getattr(msg, 'sms_content', getattr(msg, 'text', str(msg)))
            sender = getattr(msg, 'from_value', 'Unknown')
            
            # Safely extract and parse the API timestamp
            msg_time = None
            for attr in ['created_at', 'date_received', 'timestamp', 'date']:
                val = getattr(msg, attr, None)
                if val:
                    if isinstance(val, str):
                        try:
                            # Convert ISO string to Python datetime
                            msg_time = datetime.datetime.fromisoformat(val.replace('Z', '+00:00'))
                        except: pass
                    elif isinstance(val, datetime.datetime):
                        msg_time = val
                    break
            
            # Calculate "Seconds Ago" or "Mins Ago"
            time_str = "Just now"
            age_mins = 0
            
            if msg_time:
                # Ensure timezone math matches
                if msg_time.tzinfo is None:
                    msg_time = msg_time.replace(tzinfo=datetime.timezone.utc)
                    
                diff = now - msg_time
                age_seconds = int(diff.total_seconds())
                age_mins = age_seconds // 60
                
                if age_seconds < 60:
                    time_str = f"{max(0, age_seconds)} seconds ago"
                elif age_mins == 1:
                    time_str = "1 min ago"
                else:
                    time_str = f"{age_mins} mins ago"

            # Format the individual message
            formatted_msg = f"💬 <b>From {sender}:</b>\n<code>{msg_text}</code> ({time_str})"
            
            # Drop it into the correct time bucket!
            if age_mins <= 5:
                recent_msgs.append(formatted_msg)
            elif age_mins <= 30:
                history_msgs.append(formatted_msg)

        # 6. 🏗️ THE UI BUILDER (Decision Tree)
        if not recent_msgs and not history_msgs:
            # Scenario 3: Brand New Line (Clean & Simple)
            text = f"📭 <b>Inbox for {phone}:</b>\n\nNo messages yet. If you just requested the code on {service.capitalize()}, wait 10 seconds and click Check Again."
        
        else:
            # Scenario 1 & 2: Build the Trust UI
            text = f"📱 <b>Inbox for {phone}:</b>\n\n"
            
            text += "🟢 <b>NEW (Last 5 Mins):</b>\n"
            if recent_msgs:
                text += "\n\n".join(recent_msgs) + "\n\n"
            else:
                text += f"📭 <i>No new messages yet. If you just requested the code, wait 10 seconds and click Check Again.</i>\n\n"
            
            text += "⏳ <b>HISTORY (Last 30 Mins):</b>\n"
            if history_msgs:
                text += "\n\n".join(history_msgs)
            else:
                text += "<i>No older history for this line.</i>"

        # 7. Build Keyboard & Send
        keyboard = [
            [InlineKeyboardButton("🔄 Check Again", callback_data=f"check_sms:{rental_id}")],
            [InlineKeyboardButton("🔙 Back to Number", callback_data=f"manage_rental:{rental_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(text, parse_mode="HTML", reply_markup=reply_markup)

    except Exception as e:
        await query.edit_message_text(f"💥 Provider Error: {e}")