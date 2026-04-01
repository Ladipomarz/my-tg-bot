# My_bot/utils/otp_utils.py
from rapidfuzz import process, fuzz
from utils.db import get_connection

def get_service_search_results(user_input, is_rental=False):
    """
    Scans the correct PostgreSQL table and returns fuzzy matches.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            if is_rental:
                # 🏠 Search the Rental Table
                cur.execute("SELECT local_code, service_name FROM rental_services")
            else:
                # 🇺🇸 Search the One-Time Table (SMS only)
                cur.execute("SELECT local_code, service_name FROM services WHERE capability = 'sms'")
            rows = cur.fetchall()

    if not rows:
        return "none", None

    # Map names to codes: {'Telegram': '3846', ...}
    name_to_code = {row[1]: str(row[0]) for row in rows}
    names = list(name_to_code.keys())

    # Perform the high-speed fuzzy search
    results = process.extract(user_input, names, scorer=fuzz.WRatio, limit=3)
    if not results:
        return "none", None

    top_name, top_score, _ = results[0]

    # --- THE LOGIC GATE ---
    if top_score >= 95:
        return "exact", {"name": top_name, "code": name_to_code[top_name]}
    if top_score >= 40:
        suggestions = [{"name": r[0], "code": name_to_code[r[0]]} for r in results if r[1] >= 40]
        return "suggest", suggestions

    return "none", None