from rapidfuzz import process, fuzz
# Import your pool from wherever you initialized it
from utils.db import pool

def get_service_search_results(user_input):
    # 1. Fetch from Postgres
    with pool.connection() as conn:
        with conn.cursor() as cur:
            # We only want SMS services for now as you requested
            cur.execute("""
                SELECT local_code, service_name 
                FROM rental_services 
                WHERE capability = 'sms'
            """)
            rows = cur.fetchall()

    if not rows:
        return "none", None

    # Map names to codes: {'Telegram': '3846', ...}
    name_to_code = {row[1]: str(row[0]) for row in rows}
    names = list(name_to_code.keys())

    # 2. RapidFuzz Search (The logic gate)
    # This happens in RAM and takes < 0.01 seconds for 4k entries
    results = process.extract(user_input, names, scorer=fuzz.WRatio, limit=3)
    
    top_name, top_score, _ = results[0]

    # --- DECISION GATE ---
    if top_score >= 95:
        return "exact", {"name": top_name, "code": name_to_code[top_name]}

    if top_score >= 40:
        # Pass only matches that hit our professional threshold
        suggestions = [
            {"name": r[0], "code": name_to_code[r[0]]} 
            for r in results if r[1] >= 40
        ]
        return "suggest", suggestions

    return "none", None