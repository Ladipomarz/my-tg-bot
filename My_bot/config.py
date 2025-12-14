import os

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Always build DB path relative to this file (works locally + Railway)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database", "bot.db")

ADMIN_IDS = [123456789]  # keep yours
