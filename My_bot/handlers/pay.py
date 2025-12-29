import time
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from payments.plisio import create_plisio_invoice

PUBLIC_BASE = "https://my-tg-bot-production-9a75.up.railway.app"
SUCCESS_URL = "https://t.me/thejuicybox_bot"
FAIL_URL = "https://t.me/thejuicybox_bot"

# callback prefixes
CB_COIN = "plisio_coin:"
CB_NET = "plisio_net:"

# Coins you showed on the Plisio invoice UI
COINS = [
    ("BTC", "₿ Bitcoin"),
    ("ETH", "Ξ Ethereum"),
    ("LTC", "Ł Litecoin"),
    ("SOL", "◎ Solana"),
    ("TRX", "Tron"),
    ("XMR", "ɱ Monero"),
    ("USDT", "₮ Tether (USDT)"),
]

# USDT network options (common Plisio symbols; adjust if needed)
USDT_NETWORKS = [
    ("USDT_TRX", "USDT TRC20 (Tron)"),
    ("USDT_ETH", "USDT ERC20 (Ethereum)"),
]


async def pay_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /pay -> show coin selector
    """
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=f"{CB_COIN}{sym}")]
        for sym, label in COINS
    ])

    await update.message.reply_text(
        "Choose a coin to pay with:",
        reply_markup=kb,
    )


async def pay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles all callback buttons (coin + network).
    """
    q = update.callback_query
    await q.answer()
    data = (q.data or "").strip()

    user = update.effective_user
    amount_usd = 6.00  # change later to selector

    # Step 1: user selected a coin
    if data.startswith(CB_COIN):
        coin = data.split(":", 1)[1].strip().upper()

        # If USDT, ask network
        if coin == "USDT":
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(label, callback_data=f"{CB_NET}{sym}")]
                for sym, label in USDT_NETWORKS
            ])
            await q.edit_message_text(
                "Choose USDT network:",
                reply_markup=kb,
            )
            return

        # Otherwise generate invoice directly
        await q.edit_message_text(f"Creating invoice for ${amount_usd:.2f} in {coin}…")

        try:
            invoice_url = await create_plisio_invoice(
                order_number=f"PLISIO-{user.id}-{int(time.time())}",
                order_name=f"TG bot payment ({coin}) for user {user.id}",
                amount_usd=amount_usd,
                crypto_currency=coin,
                callback_url=f"{PUBLIC_BASE}/webhooks/plisio",
                success_url=SUCCESS_URL,
                fail_url=FAIL_URL,
            )
        except Exception as e:
            await q.edit_message_text(f"❌ Failed to create invoice:\n{e}")
            return

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💸 Pay with {coin}", url=invoice_url)]
        ])

        await q.edit_message_text(
            f"✅ Invoice created for ${amount_usd:.2f} ({coin}).",
            reply_markup=kb,
        )
        return

    # Step 2: user selected USDT network
    if data.startswith(CB_NET):
        usdt_symbol = data.split(":", 1)[1].strip().upper()

        pretty = "USDT"
        if usdt_symbol == "USDT_TRX":
            pretty = "USDT (TRC20)"
        elif usdt_symbol == "USDT_ETH":
            pretty = "USDT (ERC20)"

        await q.edit_message_text(f"Creating invoice for ${amount_usd:.2f} in {pretty}…")

        try:
            invoice_url = await create_plisio_invoice(
                order_number=f"PLISIO-{user.id}-{int(time.time())}",
                order_name=f"TG bot payment ({pretty}) for user {user.id}",
                amount_usd=amount_usd,
                crypto_currency=usdt_symbol,
                callback_url=f"{PUBLIC_BASE}/webhooks/plisio",
                success_url=SUCCESS_URL,
                fail_url=FAIL_URL,
            )
        except Exception as e:
            await q.edit_message_text(f"❌ Failed to create invoice:\n{e}")
            return

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💸 Pay with {pretty}", url=invoice_url)]
        ])

        await q.edit_message_text(
            f"✅ Invoice created for ${amount_usd:.2f} ({pretty}).",
            reply_markup=kb,
        )
        return

    # Unknown callback
    await q.edit_message_text("❌ Unknown selection. Try /pay again.")
