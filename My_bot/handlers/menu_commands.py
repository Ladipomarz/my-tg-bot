# My_bot/handlers/menu_commands.py
import asyncio
import logging
from telegram import BotCommand, Update
from telegram.ext import ContextTypes, CommandHandler
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

# Import your existing menu functions and config
from handlers.wallet_continue import open_wallet_menu
from handlers.start import handle_main_menu
from menus.main_menu import get_main_menu
from handlers.tools import open_tools_menu
from handlers.orders import open_orders_menu
from utils.auto_delete import safe_delete_user_message, delete_tracked_message,safe_send
from handlers.otp_handler import show_usa_verification_menu, otp_verification_handler
from config import SUPPORT_HANDLE

logger = logging.getLogger(__name__)

async def setup_bot_profile(tg_app):
    """Sets the bot's menu button, name, and descriptions on startup."""
    try:
        commands = [
            BotCommand("start", "🚀 Open Main Menu"),
            BotCommand("usa_number", "🇺🇸 Purchase USA Number"),
            BotCommand("other_number", "🌍 Purchase Non Number"),
            BotCommand("tools", "🧰 Open Tools"),
            BotCommand("rentals", "📱 Manage My Numbers"),
            BotCommand("orders", "📦 View Orders"), 
            BotCommand("credit", "💳 Check Balance & Topup"),
            BotCommand("help", "🛠 Support & Help")
        ]
        await tg_app.bot.set_my_commands(commands)
        await tg_app.bot.set_my_name(name="The Underground ☠️ Box") 
        await tg_app.bot.set_my_description(description="🤖 Welcome! to the underground box,🔨 We provide you with premium services.😎 \n\nClick Start below to begin. 🌍")
        await tg_app.bot.set_my_short_description(short_description="Premium Numbers & More.")
        logger.info("✅ Bot Profile and Menu Button have been updated successfully!")
    except Exception as e:
        logger.error(f"⚠️ Failed to update Bot Profile: {e}")

# --- Side Menu Command Functions ---

# ✅ New Safe Function for USA Number
async def usa_number_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    asyncio.create_task(safe_delete_user_message(update)) 
    await delete_tracked_message(context, update.effective_chat.id, "otp_instruction_msg_id")
    context.user_data["current_menu"] = "usa_number"
    
    # Opens the USA verification menu directly
    msg = await show_usa_verification_menu(update, context)
    
    # ✅ Track it so the next click cleans it up
    if msg:
        context.user_data["otp_instruction_msg_id"] = msg.message_id
    
  # ✅ New Safe Function for Non-USA Number
async def other_number_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    asyncio.create_task(safe_delete_user_message(update)) 
    await delete_tracked_message(context, update.effective_chat.id, "otp_instruction_msg_id")
    context.user_data["current_menu"] = "other_number"
    
    # Opens the "Other Country" placeholder directly
    await otp_verification_handler(update, context, message_text="🎙 Other Country \n\nComing soon…")  

async def tools_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    asyncio.create_task(safe_delete_user_message(update)) 
    await delete_tracked_message(context, update.effective_chat.id, "otp_instruction_msg_id")
    """Triggers when user clicks /tools from the side menu"""
    context.user_data["current_menu"] = "tools"
    await open_tools_menu(update, context)
    
    
async def orders_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    asyncio.create_task(safe_delete_user_message(update)) 
    await delete_tracked_message(context, update.effective_chat.id, "otp_instruction_msg_id")
    """Triggers when user clicks /orders from the side menu"""
    context.user_data["current_menu"] = "orders"
    await open_orders_menu(update, context) 
    
    
async def wallet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    asyncio.create_task(safe_delete_user_message(update)) 
    await delete_tracked_message(context, update.effective_chat.id, "otp_instruction_msg_id")
    context.user_data["current_menu"] = "wallet"
    await open_wallet_menu(update, context)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Standard Cleanup
    asyncio.create_task(safe_delete_user_message(update))
    from utils.auto_delete import delete_tracked_message
    await delete_tracked_message(context, update.effective_chat.id, "otp_instruction_msg_id")

    # 2. Unified text
    help_text = (
        "💡 <b>Help & Support</b>\n\n"
        "Need assistance with your orders or balance?\n"
        f"Contact our team here: {SUPPORT_HANDLE}"
    )

    # 3. USE THE MAIN MENU TO KEEP THE 4-DOTS ALIVE
    # (We sacrifice the Inline "Close" button to keep the keypad visible)
    msg = await safe_send(
        update,
        context,
        text=help_text,
        reply_markup=get_main_menu() # 👈 This forces the 4-dots to stay
    )

    # 4. Save ID so the Janitor deletes it when they click something else
    if msg:
        context.user_data["otp_instruction_msg_id"] = msg.message_id

def register_side_menu(tg_app):
    """Locks everything into a single function to be called in bot.py"""
    tg_app.add_handler(CommandHandler("usa_number", usa_number_cmd))
    tg_app.add_handler(CommandHandler("other_number", other_number_cmd))
    tg_app.add_handler(CommandHandler("credit", wallet_cmd))
    tg_app.add_handler(CommandHandler("orders", orders_cmd))
    tg_app.add_handler(CommandHandler("help", help_cmd))
    tg_app.add_handler(CommandHandler("tools", tools_cmd))