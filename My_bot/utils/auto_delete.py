import asyncio
import os
import logging
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


from telegram import Update, ReplyKeyboardMarkup
import asyncio

async def safe_send(
    update_or_query,
    context,
    text: str,
    reply_markup=None,
    parse_mode=None, 
    chat_id: int = None,
    **kwargs 
):
    """
    Sends a bot message and deletes the previous bot message AFTER a delay,
    BUT never deletes the message that contains the ReplyKeyboardMarkup.
    Now safely handles background alarms where update_or_query is None!
    """

    # 🛑 THE MAGIC AUTO-APPENDER 🛑
    if any(word in text.lower() for word in ["❌", "⚠️", "failed", "error", "invalid"]):
        from config import SUPPORT_HANDLE
        # Prevent doubling it up if you already included it in the text
        if f"Contact {SUPPORT_HANDLE}" not in text: 
            text = f"{text}\n\n🛠 <b>Need help? Contact {SUPPORT_HANDLE}</b>"

    # ✅ 1. Detect source safely (Handles Background Jobs now!)
    base_msg = None
    if isinstance(update_or_query, Update):
        chat_id = chat_id or update_or_query.effective_chat.id
        base_msg = update_or_query.effective_message
    elif update_or_query is not None:
        # It's a CallbackQuery
        chat_id = chat_id or update_or_query.message.chat_id
        base_msg = update_or_query.message

    if not chat_id:
        return None # Failsafe if we have absolutely no way to know where to send

    # ✅ 2. Delete previous bot message
    last_id = context.user_data.get("last_bot_message_id")
    last_had_reply_kb = context.user_data.get("last_bot_message_had_reply_kb", False)

    if last_id and not last_had_reply_kb:
        from config import PREVIOUS_MESSAGE_DELAY_SECONDS
        # Make sure _delete_after_delay is defined in this file!
        asyncio.create_task(
            _delete_after_delay(
                context,
                chat_id,
                last_id,
                PREVIOUS_MESSAGE_DELAY_SECONDS
            )
        )
        
    actual_mode = parse_mode or kwargs.get("parse_mode", "HTML")
    clean_kwargs = {k: v for k, v in kwargs.items() if k != "parse_mode"}

    # ✅ 3. Send the message safely
    try:
        if base_msg:
            # Triggered by a user typing or clicking a button
            msg = await base_msg.reply_text(
                text=text, 
                reply_markup=reply_markup, 
                parse_mode=actual_mode,
                **clean_kwargs 
            )
        else:
            # Triggered by a background job (like connection error or 6h warning)
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=actual_mode,
                **clean_kwargs
            )

        # Remember this as the new "last" bot message
        context.user_data["last_bot_message_id"] = msg.message_id
        context.user_data["last_bot_message_had_reply_kb"] = isinstance(reply_markup, ReplyKeyboardMarkup)
        return msg

    except Exception as e:
        logging.getLogger(__name__).error(f"safe_send failed: {e}")
        return None

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


