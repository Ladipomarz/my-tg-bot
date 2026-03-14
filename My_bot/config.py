import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")  # from Railway
SMSA_API_KEY = os.getenv("SMSA_API_KEY", "").strip()
SUPPORT_HANDLE = os.getenv("SUPPORT_HANDLE", "@YourSupportUsername")

# 🧪 MOCK MODE SWITCH
MOCK_MODE = os.getenv("MOCK_MODE", "False").lower() == "true"
# How long (seconds) before the bot deletes its previous message
PREVIOUS_MESSAGE_DELAY_SECONDS = 2

# 👑 DYNAMIC ADMIN IDS FROM RAILWAY
# This grabs the variable from Railway. If it's missing, it defaults to empty.
raw_admin_ids = os.getenv("ADMIN_IDS", "")

# This safely converts a string like "1234567,9876543" into a proper Python list of numbers
ADMIN_IDS = [int(admin_id.strip()) for admin_id in raw_admin_ids.split(",") if admin_id.strip().isdigit()]


if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing or not set!")

# config.py

# TextVerified API credentials
TEXTVERIFIED_API_KEY = os.getenv("TEXTVERIFIED_API_KEY")  # For TextVerified API
TEXTVERIFIED_API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")  # For TextVerified API (if needed)