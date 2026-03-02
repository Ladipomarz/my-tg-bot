# handlers/service_list_flow.py
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from handlers.otp_handler import send_services_txt  # the function that builds/sends txt from DB


def _yes_skip_keyboard(*, back_callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, I have the Product ID", callback_data="otp_have_id"),
            InlineKeyboardButton("⏭ Skip", callback_data="otp_skip_universal"),
        ],
        [InlineKeyboardButton("⬅ Back", callback_data=back_callback)],
    ])



async def start_service_list_flow(update, context, *, plan: str, capability: str = "sms") -> None:
    """
    plan: 'one_time'  (stored in user_data)
    Sends:
      1) message: sending file
      2) txt document (from DB)
      3) message: yes/skip + buttons
    """
    q = update.callback_query
    context.user_data["otp_plan"] = plan

    # 1) short message
    try:
        await q.edit_message_text("📄 Here is the service list. Sending the file now...")
    except Exception:
        pass

    # 2) txt file
    await send_services_txt(update, context, capability=capability)

    # 3) yes/skip message + buttons
    kb = _yes_skip_keyboard(back_callback="otp_back_usa_one_time_rental")
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            "If you've got the 4-digit Product ID, click ✅ Yes to continue.\n"
            "If you couldn't find the service you need, click ⏭ Skip to get a universal phone number.\n\n"
            "⚠️ Please make sure the service is not listed before using the universal phone number, "
            "or it may not receive OTP codes."
        ),
        reply_markup=kb,
    )
