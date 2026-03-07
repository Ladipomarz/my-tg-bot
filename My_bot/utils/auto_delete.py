import asyncio
import os
import html
from config import SUPPORT_HANDLE

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

# How long after a NEW action before the PREVIOUS bot message disappears
PREVIOUS_MESSAGE_DELAY_SECONDS = 2

SUPPORT_HANDLE = os.getenv("SUPPORT_HANDLE", "@YourSupportUsername") # Put this near the top of the file


async def _delete_after_delay(context, chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        # Ignore if already deleted / can't delete
        pass


async def safe_send(
    update_or_query,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup=None,
    **kwargs 
):
    
    # 🛑 THE MAGIC AUTO-APPENDER 🛑
    # By using text.lower(), you catch "Failed", "FAILED", "failed", "Error", "ERROR", etc.!
    if "❌" in text or "⚠️" in text or "failed" in text.lower() or "error" in text.lower() or "invalid" in text.lower():
        text = f"{text}\n\n🛠 <b>Need help? Contact {SUPPORT_HANDLE}</b>"
        
    """
    Sends a bot message and deletes the previous bot message AFTER a delay,
    BUT never deletes the message that contains the ReplyKeyboardMarkup
    (Tools/Orders), otherwise Telegram hides the keyboard.
    """

    # Detect source (Update or CallbackQuery)
    if isinstance(update_or_query, Update):
        chat_id = update_or_query.effective_chat.id
        base_msg = update_or_query.effective_message
    else:
        query = update_or_query
        chat_id = query.message.chat_id
        base_msg = query.message

    # ✅ Delete previous bot message ONLY if it did NOT contain a reply keyboard
    last_id = context.user_data.get("last_bot_message_id")
    last_had_reply_kb = context.user_data.get("last_bot_message_had_reply_kb", False)

    if last_id and not last_had_reply_kb:
        asyncio.create_task(
            _delete_after_delay(
                context,
                chat_id,
                last_id,
                PREVIOUS_MESSAGE_DELAY_SECONDS,
                
            )
        )

    # Send new message
    msg = await base_msg.reply_text(text, reply_markup=reply_markup, **kwargs)

    # Remember this as the new "last" bot message
    context.user_data["last_bot_message_id"] = msg.message_id
    context.user_data["last_bot_message_had_reply_kb"] = isinstance(reply_markup, ReplyKeyboardMarkup)

    return msg

async def safe_delete_user_message(update):
    """
    Best-effort delete of user's message (private chats, <48h).
    Does nothing if deletion is not allowed.
    """
    try:
        if update and update.message:
            await asyncio.sleep(10)
            await update.message.delete()
    except Exception:
        pass
    


async def delete_tracked_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    key: str,
):
    """
    Deletes a bot message whose message_id is stored in context.user_data[key]
    """
    msg_id = context.user_data.pop(key, None)
    if not msg_id:
        return
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=int(msg_id))
    except Exception:
        pass


