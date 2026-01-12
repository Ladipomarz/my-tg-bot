import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")  # from Railway

ADMIN_IDS = [123456789]  # keep your real admin IDs
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing set")

# config.py

# TextVerified API credentials
TEXTVERIFIED_API_KEY = os.getenv("TEXTVERIFIED_API_KEY")  # For TextVerified API
TEXTVERIFIED_API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")  # For TextVerified API (if needed)