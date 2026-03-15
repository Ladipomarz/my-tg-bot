import os
import logging
from telegram import Update
import asyncio
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Pull variables directly from your Railway environment / config
from config import ADMIN_IDS
SUPPORT_BOT_TOKEN = os.getenv("SUPPORT_BOT_TOKEN", "").strip()

logger = logging.getLogger("support_bot")
logger.setLevel(logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command for the Support Bot"""
    user_id = update.effective_user.id
    
    if user_id in ADMIN_IDS:
        await update.message.reply_text(
            "👨‍💻 **Admin Mode Active**\n\nWhen a user sends a ticket, it will appear here. Simply **Swipe/Reply** to their message to send an answer back.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "👋 **Welcome to Underground Box Support!**\n\n"
            "Please describe your issue in a single message below, and our team will get back to you shortly.",
            parse_mode="Markdown"
        )

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Routes messages between Users and Admins"""
    user_id = update.effective_user.id
    text = update.message.text
    
    if not text:
        return 

    # -----------------------------------------
    # 🔓 1. IF ADMIN IS REPLYING TO A USER
    # -----------------------------------------
    if user_id in ADMIN_IDS and update.message.reply_to_message:
        original_msg = update.message.reply_to_message.text
        
        try:
            # Extracts the User ID from the ticket text
            target_user_id = int(original_msg.split("User ID: ")[1].split("\n")[0])
            
            # Send the admin's reply back to the user
            await context.bot.send_message(
                chat_id=target_user_id, 
                text=f"👨‍💻 **Message from Support:**\n\n{text}",
                parse_mode="Markdown"
            )
            await update.message.reply_text("✅ Reply sent to user.")
            
        except Exception:
            await update.message.reply_text("❌ Could not send. Make sure you are replying directly to a Ticket message.")
        return

    # -----------------------------------------
    # 🛑 2. IF ADMIN TYPES NORMALLY (Not replying)
    # -----------------------------------------
    if user_id in ADMIN_IDS and not update.message.reply_to_message:
        await update.message.reply_text("⚠️ To reply to a user, you must **Swipe Right / Reply** to their specific ticket message.")
        return

    # -----------------------------------------
    # 📩 3. IF A NORMAL USER SENDS A MESSAGE
    # -----------------------------------------
    if user_id not in ADMIN_IDS:
        username = f"@{update.effective_user.username}" if update.effective_user.username else "No Username"
        
        ticket = (
            f"📩 **NEW TICKET**\n"
            f"User ID: {user_id}\n"
            f"Username: {username}\n\n"
            f"📝 **Message:**\n{text}"
        )
        
        for admin in ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin, text=ticket)
            except Exception:
                pass
                
        await update.message.reply_text("✅ Message sent! We will reply here soon.")

# 🚀 THE BOOTSTRAPPER (in supportbot.py)
async def run_support_bot():
    if not SUPPORT_BOT_TOKEN:
        logger.warning("No SUPPORT_BOT_TOKEN found. Support Bot is disabled.")
        return

    support_app = ApplicationBuilder().token(SUPPORT_BOT_TOKEN).build()
    
    support_app.add_handler(CommandHandler("start", start))
    support_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    
    await support_app.initialize()
    await support_app.start()
    
    logger.info("⏳ Waiting 20 seconds for old bot instance to shut down...")
    await asyncio.sleep(20)
    
    # ✅ THE CORRECT LINE: drop_pending_updates clears the old "Conflict" session
    await support_app.updater.start_polling(drop_pending_updates=True)
    
    logger.info("✅ Support Bot session seized and running.")