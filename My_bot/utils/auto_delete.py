import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest

# How long after a NEW action before the PREVIOUS bot message disappears
PREVIOUS_MESSAGE_DELAY_SECONDS = 2


async def _delete_after_delay(context, chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except BadRequest:
        # already deleted / can't delete (e.g. message not found)
        pass
    except Exception:
        # ignore anything else (message too old, no rights, etc.)
        pass


async def safe_send(
    update_or_query,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup=None,
):
    """
    GLOBAL SENDER:
    - Sends a bot message (reply_text)
    - Remembers its message_id as "last bot message"
    - Deletes:
        (a) the previous bot message after PREVIOUS_MESSAGE_DELAY_SECONDS
        (b) the inline-keyboard message that was clicked (if called from a CallbackQuery)

    Works for both:
    - Update (normal messages)
    - CallbackQuery (button presses)
    """

    # Detect source (Update or CallbackQuery)
    if isinstance(update_or_query, Update):
        chat_id = update_or_query.effective_chat.id
        base_msg = update_or_query.effective_message
        clicked_message_id = None
    else:
        # CallbackQuery
        query = update_or_query
        chat_id = query.message.chat_id
        base_msg = query.message
        clicked_message_id = query.message.message_id

    # If the user clicked an inline keyboard, delete that menu message too
    if clicked_message_id:
        asyncio.create_task(
            _delete_after_delay(
                context,
                chat_id,
                clicked_message_id,
                PREVIOUS_MESSAGE_DELAY_SECONDS,
            )
        )

    # Delete previous bot message after a short delay
    last_id = context.user_data.get("last_bot_message_id")
    if last_id and last_id != clicked_message_id:
        asyncio.create_task(
            _delete_after_delay(
                context,
                chat_id,
                last_id,
                PREVIOUS_MESSAGE_DELAY_SECONDS,
            )
        )

    # Send new message
    msg = await base_msg.reply_text(text, reply_markup=reply_markup)

    # Remember this as the new "last" bot message
    context.user_data["last_bot_message_id"] = msg.message_id

    return msg
