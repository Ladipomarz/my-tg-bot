import os
import asyncio
from telegram import Bot

async def main():
    bot = Bot(os.environ["BOT_TOKEN"])
    await bot.delete_webhook(drop_pending_updates=True)
    print("Webhook deleted + pending updates dropped")

asyncio.run(main())
