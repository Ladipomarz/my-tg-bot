from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from utils.db import get_rental_by_id, debit_balance, extend_rental, cancel_rental,get_connection
from menus.main_menu import get_main_menu  # Main menu handler


import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Example logging inside rental handler
logger.debug("Processing rental renewal for rental_id: %s", rental_id)


# Renew rental if the balance is sufficient
async def renew_rental_handler(update, context, rental_id):
    try:
        conn = get_connection()  # Get a fresh connection
        cursor = conn.cursor()

        # Fetch rental data from DB
        cursor.execute("SELECT * FROM rentals WHERE rental_id = %s", (rental_id,))
        rental = cursor.fetchone()

        if rental is None:
            await update.message.reply_text("❌ Rental not found.")
            return

        # Check user balance
        if rental['balance'] >= rental['renewal_price']:
            # Proceed with auto-renew if balance is sufficient
            await process_auto_renewal(rental)
        else:
            # Insufficient balance, send top-up message
            await send_top_up_message(update)

        conn.close()

    except Exception as e:
        logger.error(f"Error in renew_rental_handler: {str(e)}")
        await update.message.reply_text(f"❌ An error occurred: {str(e)}")

# Send message if balance is insufficient for renewal
async def send_top_up_message(update):
    await update.message.reply_text(
        "You don’t have enough balance to renew. Please top up your wallet to continue."
    )
    
    # Add button to redirect user to wallet menu for top-up
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Top-up Wallet", callback_data="top_up_wallet")]
    ])
    
    await update.message.reply_text(
        "Click the button below to top up your wallet.",
        reply_markup=kb
    )

# Redirect to top-up page
async def top_up_wallet_handler(update, context):
    # Redirect user to wallet top-up page
    await show_wallet_menu(update, context)

# Show wallet menu where user can top up
async def show_wallet_menu(update, context):
    await update.message.reply_text(
        "Please select your payment method to top up your wallet.",
        reply_markup=wallet_menu_keyboard()  # Replace with actual wallet menu
    )

# Process auto-renewal of the rental
async def process_auto_renewal(rental):
    # Deduct balance and renew rental
    debit_balance(rental['user_id'], rental['renewal_price'])
    extend_rental(rental['rental_id'])
    
    # Notify user about renewal success
    await rental['user_id'].send_message(f"Your rental has been successfully renewed for another {rental['renewal_period']}.")

# Handle the cancellation of rental
async def cancel_rental(update, context, rental_id):
    rental = get_rental_by_id(rental_id)
    
    # Remove rental from DB or mark it as canceled
    cancel_rental(rental_id)
    
    # Notify the user that the rental has been canceled
    await update.callback_query.answer("Your rental has been canceled.")

    # Show the main menu or other options
    await show_main_menu(update, context)

# Example of a main menu after cancellation
async def show_main_menu(update, context):
    await update.message.reply_text(
        "You have successfully canceled the rental. Choose an option to proceed.",
        reply_markup=get_main_menu()  # Replace with your main menu buttons
    )

# Utility function to create wallet menu keyboard (for top-up)
def wallet_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Pay with Credit Card", callback_data="pay_credit_card")],
        [InlineKeyboardButton("Pay with PayPal", callback_data="pay_paypal")],
    ])
