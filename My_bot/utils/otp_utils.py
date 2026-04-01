# My_bot/utils/otp_utils.py
from rapidfuzz import process, fuzz
from utils.db import get_connection

def get_service_search_results(user_input):
    user_input = user_input.strip() # Clean the input first
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT local_code, service_name FROM services WHERE capability = 'sms'")
            rows = cur.fetchall()

    if not rows: return "none", None

    name_to_code = {row[1]: str(row[0]) for row in rows}
    names = list(name_to_code.keys())

    # ✅ 1. THE TRUMP CARD: Direct Case-Insensitive Match
    # If they typed "Telegram", "telegram", or "TELEGRAM", this catches it instantly.
    user_lower = user_input.lower()
    for name in names:
        if name.strip().lower() == user_lower:
            return "exact", {"name": name, "code": name_to_code[name]}

    # 2. FUZZY SEARCH (For actual typos like "Telegrum")
    results = process.extract(user_input, names, scorer=fuzz.QRatio, limit=3)
    
    if not results: return "none", None
    
    top_name, top_score, _ = results[0]

    if top_score >= 95:
        return "exact", {"name": top_name, "code": name_to_code[top_name]}

    if top_score >= 50:
        suggestions = [{"name": r[0], "code": name_to_code[r[0]]} for r in results if r[1] >= 50]
        return "suggest", suggestions

    return "none", None