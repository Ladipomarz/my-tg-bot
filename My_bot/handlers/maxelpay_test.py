import time
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from payments.maxelpay import create_maxelpay_checkout


async def test_maxelpay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    await update.message.reply_text("Creating MaxelPay test checkout…")

    try:
        url = await create_maxelpay_checkout(
            order_id=f"TEST-{user.id}-{int(time.time())}",
            amount_usd=5.00,
            user_id=user.id,  # ✅ NOW VALID
            user_name=user.first_name or "Telegram User",
            user_email=(
                f"{user.username}@telegram.local"
                if user.username
                else "telegram@user.local"
            ),
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error:\n{e}")
        return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Open MaxelPay Checkout", url=url)]
    ])

    await update.message.reply_text(
        "✅ MaxelPay checkout created:",
        reply_markup=kb,
    )
