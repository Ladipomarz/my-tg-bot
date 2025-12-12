# utils/flow.py
import asyncio
from telegram import Update
from telegram.ext import ContextTypes

# Helper: detect if this is from /text or from a button
def _get_chat_and_message(update_or_query):
    if isinstance(update_or_query, Update):
        chat_id = update_or_query.effective_chat.id
        source_msg = update_or_query.message
    else:
        # callback query object
        chat_id = update_or_query.message.chat_id
        source_msg = update_or_query.message
    return chat_id, source_msg


async def flow_send(
    flow_name: str,
    update_or_query,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup=None,
):
    """
    Send a new message for a given flow and remember it for later cleanup.
    Does NOT delete old messages immediately (chat scrolls normally).
    """
    chat_id, source_msg = _get_chat_and_message(update_or_query)

    key = f"{flow_name}_messages"
    ids = context.user_data.get(key) or []

    msg = await source_msg.reply_text(text, reply_markup=reply_markup)
    ids.append(msg.message_id)
    context.user_data[key] = ids

    return msg


async def flow_finish(
    flow_name: str,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    delay_seconds: int = 60,
):
    """
    After delay_seconds, delete all messages that were sent via flow_send()
    for that flow.
    """
    key = f"{flow_name}_messages"
    ids = list(context.user_data.get(key) or [])
    context.user_data[key] = []

    if not ids:
        return

    async def _cleanup(delete_ids):
        await asyncio.sleep(delay_seconds)
        for mid in delete_ids:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=mid)
            except Exception:
                pass

    asyncio.create_task(_cleanup(ids))
