import os
import httpx
import logging

logger = logging.getLogger(__name__)


ADMIN_ID = os.getenv("ADMIN_ID")
BOT_TOKEN = os.getenv("BOT_TOKEN") # The same token your bot uses!

async def notify_admin(error_message: str):
    """
    Universally snipes an error to the Admin from ANYWHERE in the code.
    Does NOT need 'context' or 'update'.
    """
    if not ADMIN_ID or not BOT_TOKEN:
        return
        
    safe_error = str(error_message)[:3500] # Prevent Telegram length limits
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": ADMIN_ID,
        "text": f"🚨 BOT ALERT:\n{safe_error}"
    }
    
    try:
        # Fire the message directly to Telegram's server
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(url, json=payload)
    except Exception:
        pass # Silently fail if there is a network glitch


def notify_admin_sync(error_message: str):
    """
    A synchronous sniper specifically for db.py.
    No 'await' or 'async' needed!
    """
    if not ADMIN_ID or not BOT_TOKEN:
        return
        
    safe_error = str(error_message)[:3500]
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": ADMIN_ID,
        "text": f"🚨 DB CRASH:\n{safe_error}"
    }
    
    try:
        # Notice we use the standard sync Client here!
        with httpx.Client(timeout=5) as client:
            client.post(url, json=payload)
    except Exception:
        pass