import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")  # from Railway

ADMIN_IDS = [123456789]  # keep your real admin IDs
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing set")

# config.py

OTP_PROVIDER_MODE = "mock"  # Change to "textverified" when going live
API_KEY = "your_real_textverified_api_key_here"  # Only needed for live mode
