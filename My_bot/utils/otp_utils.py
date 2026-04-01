# My_bot/utils/otp_utils.py
from rapidfuzz import process, fuzz
from utils.db import get_connection

def get_service_search_results(user_input):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT local_code, service_name FROM services WHERE capability = 'sms'")
            rows = cur.fetchall()

    if not rows: return "none", None

    name_to_code = {row[1]: str(row[0]) for row in rows}
    names = list(name_to_code.keys())

    # ✅ THE FIX: Use QRatio instead of WRatio for stricter matching
    results = process.extract(user_input, names, scorer=fuzz.QRatio, limit=3)
    
    if not results: return "none", None
    
    top_name, top_score, _ = results[0]

    # 1. EXACT MATCH (Still 95%+)
    if top_score >= 95:
        return "exact", {"name": top_name, "code": name_to_code[top_name]}

    # 2. SUGGESTION GATE (Bumped to 50% for extra safety)
    if top_score >= 50:
        suggestions = [{"name": r[0], "code": name_to_code[r[0]]} for r in results if r[1] >= 50]
        return "suggest", suggestions

    # 3. HARD STOP (Anything below 50% is now considered gibberish)
    return "none", None