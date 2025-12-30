import asyncio
from telegram import Update
from telegram.error import BadRequest

# ⏱ how long before old messages disappear
PREVIOUS_MESSAGE_DELAY_SECONDS = 2


async def _delete_after_delay(context, chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(
            chat_id=chat_id,
            message_id=message_id,
        )
    except BadRequest:
        # message already deleted / too old
        pass
    except Exception:
        pass


async def safe_send(update_or_query, context, text: str, reply_markup=None):
    """
    Sends a bot message and automatically deletes:
    1) the previously sent bot message
    2) the inline keyboard message the user just clicked (if any)
    """

    # ── Determine call source ─────────────────────────────
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

    # ── Delete clicked inline keyboard ────────────────────
    if clicked_message_id:
        asyncio.create_task(
            _delete_after_delay(
                context,
                chat_id,
                clicked_message_id,
                PREVIOUS_MESSAGE_DELAY_SECONDS,
            )
        )

    # ── Delete previous bot message ───────────────────────
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

    # ── Send new message ──────────────────────────────────
    msg = await base_msg.reply_text(
        text=text,
        reply_markup=reply_markup,
    )

    context.user_data["last_bot_message_id"] = msg.message_id
    return msg
