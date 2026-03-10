# My_bot/handlers/menu_commands.py
import asyncio
import logging
from telegram import BotCommand, Update
from telegram.ext import ContextTypes, CommandHandler

# Import your existing menu functions and config
from handlers.wallet_continue import open_wallet_menu
from handlers.start import handle_main_menu
from menus.main_menu import get_main_menu
from handlers.tools import open_tools_menu
from handlers.orders import open_orders_menu
from utils.auto_delete import safe_delete_user_message, delete_tracked_message
from config import SUPPORT_HANDLE

logger = logging.getLogger(__name__)

async def setup_bot_profile(tg_app):
    """Sets the bot's menu button, name, and descriptions on startup."""
    try:
        commands = [
            BotCommand("start", "🚀 Open Main Menu"),
            BotCommand("tools", "🧰 Open Tools"),
            BotCommand("rentals", "📱 Manage My Numbers"),
            BotCommand("orders", "📦 View Orders"), 
            BotCommand("credit", "💳 Check Balance & Topup"),
            BotCommand("help", "🛠 Support & Help")
        ]
        await tg_app.bot.set_my_commands(commands)
        await tg_app.bot.set_my_name(name="The Underground ☠️ Box") 
        await tg_app.bot.set_my_description(description="🤖 Welcome! to the underground box,🔨 We provide you with premium services.😎 \n\nClick Start below to begin. 🌍")
        await tg_app.bot.set_my_short_description(short_description="Premium Numbers & eSIMs.")
        logger.info("✅ Bot Profile and Menu Button have been updated successfully!")
    except Exception as e:
        logger.error(f"⚠️ Failed to update Bot Profile: {e}")

# --- Side Menu Command Functions ---
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
    asyncio.create_task(safe_delete_user_message(update)) 
    await delete_tracked_message(context, update.effective_chat.id, "otp_instruction_msg_id")
    """Triggers when user clicks /help from the side menu"""
    # Notice we added reply_markup=get_main_menu() here!
    await update.message.reply_text(
        f"🛠 Need help? Contact {SUPPORT_HANDLE}", 
        reply_markup=get_main_menu()
    )

def register_side_menu(tg_app):
    """Locks everything into a single function to be called in bot.py"""
    tg_app.add_handler(CommandHandler("credit", wallet_cmd))
    tg_app.add_handler(CommandHandler("orders", orders_cmd))
    tg_app.add_handler(CommandHandler("help", help_cmd))
    tg_app.add_handler(CommandHandler("tools", tools_cmd))