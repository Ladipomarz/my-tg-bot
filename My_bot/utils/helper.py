import httpx
import logging
from config import SUPPORT_HANDLE, BOT_TOKEN, ADMIN_IDS # We only use config now!

logger = logging.getLogger(__name__)

# ✂️ Notice we completely deleted the os.getenv() lines here!

async def notify_admin(error_message: str):
    """
    Universally snipes an error to ALL Admins from ANYWHERE in the code.
    """
    if not ADMIN_IDS or not BOT_TOKEN:
        print("⚠️ SNIPER ABORTED: ADMIN_IDS or BOT_TOKEN is missing in config!")
        return
        
    safe_error = str(error_message)[:3500]
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    # Safety check: make sure ADMIN_IDS is treated as a list
    admin_list = ADMIN_IDS if isinstance(ADMIN_IDS, list) else [ADMIN_IDS]

    # Open ONE connection, but fire MULTIPLE shots (one for each admin)
    async with httpx.AsyncClient(timeout=5) as client:
        for admin_id in admin_list:
            payload = {
                "chat_id": admin_id,
                "text": f"🚨 BOT ALERT:\n{safe_error}"
            }
            try:
                await client.post(url, json=payload)
            except Exception as e:
                print(f"⚠️ SNIPER MISSED for Admin {admin_id}: {e}")


def notify_admin_sync(error_message: str):
    """
    A synchronous sniper specifically for db.py. Sends to ALL Admins.
    """
    if not ADMIN_IDS or not BOT_TOKEN:
        print("⚠️ SNIPER ABORTED: ADMIN_IDS or BOT_TOKEN is missing in config!")
        return
        
    safe_error = str(error_message)[:3500]
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    admin_list = ADMIN_IDS if isinstance(ADMIN_IDS, list) else [ADMIN_IDS]

    with httpx.Client(timeout=5) as client:
        for admin_id in admin_list:
            payload = {
                "chat_id": admin_id,
                "text": f"🚨 DB CRASH:\n{safe_error}"
            }
            try:
                client.post(url, json=payload)
            except Exception as e:
                print(f"⚠️ SNIPER MISSED for Admin {admin_id}: {e}")