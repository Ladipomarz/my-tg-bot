# handlers/service_list_flow.py
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from handlers.otp_handler import send_services_txt  # the function that builds/sends txt from DB
from utils.auto_delete import safe_send
from utils.helper import notify_admin
from menus.main_menu import get_main_menu  # 👈 This connects the menu to your handler


def _yes_skip_keyboard(*, back_callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, I have the Service ID", callback_data="otp_have_id"),
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

    # 1) Use triple quotes for the instructions
    instruction_text = """
    📄 <b>Kindly Open The File Below</b> 
    Search or find the service you want to get an OTP for.

    When you find it, copy out the <b>4 Digit Code</b>. 
    That is your Service ID.
    """

    try:
        await safe_send(
            update,
            context,
            instruction_text,
            reply_markup=get_main_menu() # 👈 The "Safety Pin"
        )
    except Exception as e:
        await notify_admin(f"Sending service list Failed: {e}")

    # 2) txt file
    await send_services_txt(update, context, capability=capability)

   # 3) yes/skip message + buttons
    kb = _yes_skip_keyboard(back_callback="otp_back_usa_one_time_rental")
    
    # 👇 Changed to safe_send and removed chat_id! 👇
    await safe_send(
        update,
        context,
        text=(
            "If you've got the 4-digit Service ID, click ✅ Yes to continue.\n"
            "If you couldn't find the service you need, after searching the Service List, click ⏭ Skip to get a universal phone number.\n\n"
            "⚠️ Please make sure the service is not in the List sent above before using the universal phone number, "
            "or you will not receive your code"
        ),
        reply_markup=kb,
    )
    
    # 👇 1. WE SET THE TRAP HERE 👇
    context.user_data["otp_step"] = "awaiting_otp_button"


# 👇 2. WE ADD THE REPROMPT HELPER HERE 👇
async def resend_otp_menu(update, context):
    """Silently pushes the One-Time OTP buttons back to the user if they type text."""
    kb = _yes_skip_keyboard(back_callback="otp_back_usa_one_time_rental")
    await safe_send(
        update,
        context,
        "⚠️ <b>Please click an option below:</b>", 
        reply_markup=kb, 
        parse_mode="HTML"
    )