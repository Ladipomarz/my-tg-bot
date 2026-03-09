import asyncio
import os
import html
from config import SUPPORT_HANDLE,PREVIOUS_MESSAGE_DELAY_SECONDS

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

# How long after a NEW action before the PREVIOUS bot message disappears


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
    parse_mode=None, # 👈 Added to function signature
    **kwargs 
):
    """
    Sends a bot message and deletes the previous bot message AFTER a delay,
    BUT never deletes the message that contains the ReplyKeyboardMarkup.
    """

    # 🛑 THE MAGIC AUTO-APPENDER 🛑
    if any(word in text.lower() for word in ["❌", "⚠️", "failed", "error", "invalid"]):
        from config import SUPPORT_HANDLE
        text = f"{text}\n\n🛠 <b>Need help? Contact {SUPPORT_HANDLE}</b>"

    # Detect source (Update or CallbackQuery)
    if isinstance(update_or_query, Update):
        chat_id = update_or_query.effective_chat.id
        base_msg = update_or_query.effective_message
    else:
        query = update_or_query
        chat_id = query.message.chat_id
        base_msg = query.message

    # ✅ Delete previous bot message
    last_id = context.user_data.get("last_bot_message_id")
    last_had_reply_kb = context.user_data.get("last_bot_message_had_reply_kb", False)

    if last_id and not last_had_reply_kb:
        from config import PREVIOUS_MESSAGE_DELAY_SECONDS
        asyncio.create_task(
            _delete_after_delay(
                context,
                chat_id,
                last_id,
                PREVIOUS_MESSAGE_DELAY_SECONDS
            )
        )
        
    # ✅ FIX: Define the parse mode properly
    # If a specific mode was passed, use it. Otherwise, default to HTML.
    actual_mode = parse_mode or kwargs.get("parse_mode", "HTML")

    # ✅ FIX: Pass the arguments cleanly. 
    # Don't pass parse_mode twice!
    msg = await base_msg.reply_text(
        text=text, 
        reply_markup=reply_markup, 
        parse_mode=actual_mode,
        **{k: v for k, v in kwargs.items() if k != "parse_mode"} # Avoid duplicates
    )

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


