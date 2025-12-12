import sqlite3
import datetime
import random
from config import DB_PATH


def get_connection():
    return sqlite3.connect(DB_PATH)


def create_tables():
    conn = get_connection()
    cursor = conn.cursor()

    # Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        first_name TEXT,
        username TEXT,
        is_admin INTEGER DEFAULT 0
    )
    """)

    # Orders table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        order_code TEXT UNIQUE,
        status TEXT,              -- 'pending', 'completed', 'cancelled'
        description TEXT,
        created_at TEXT
    )
    """)

    conn.commit()
    conn.close()


# ---------- Users helpers ----------

def add_user(user_id, first_name, username, is_admin=0):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT OR IGNORE INTO users (user_id, first_name, username, is_admin)
    VALUES (?, ?, ?, ?)
    """, (user_id, first_name, username, is_admin))

    conn.commit()
    conn.close()


def get_user(user_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()

    conn.close()
    return user


# ---------- Orders helpers ----------

def _generate_order_code(cursor) -> str:
    """
    Generate a unique random 9-digit order id ending with '#', e.g. '482910375#'.
    """
    while True:
        num = random.randint(100_000_000, 999_999_999)  # 9 digits
        code = f"{num}#"
        cursor.execute("SELECT 1 FROM orders WHERE order_code = ?", (code,))
        if not cursor.fetchone():
            return code


def create_order(user_id: int, description: str = "") -> tuple:
    """
    Create a new pending order for user_id.
    Returns (id, order_code).
    """
    conn = get_connection()
    cursor = conn.cursor()

    order_code = _generate_order_code(cursor)
    created_at = datetime.datetime.utcnow().isoformat()

    cursor.execute("""
    INSERT INTO orders (user_id, order_code, status, description, created_at)
    VALUES (?, ?, 'pending', ?, ?)
    """, (user_id, order_code, description, created_at))

    conn.commit()

    order_id = cursor.lastrowid
    conn.close()
    return order_id, order_code


def get_pending_order(user_id: int):
    """
    Get the most recent pending order for a user, or None.
    Returns row: (id, user_id, order_code, status, description, created_at)
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, user_id, order_code, status, description, created_at
    FROM orders
    WHERE user_id = ? AND status = 'pending'
    ORDER BY id DESC
    LIMIT 1
    """, (user_id,))

    row = cursor.fetchone()
    conn.close()
    return row


def update_order_status(order_id: int, status: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    UPDATE orders
    SET status = ?
    WHERE id = ?
    """, (status, order_id))

    conn.commit()
    conn.close()


def set_order_description(order_id: int, description: str):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    UPDATE orders
    SET description = ?
    WHERE id = ?
    """, (description, order_id))

    conn.commit()
    conn.close()


def get_orders_for_user(user_id: int, limit: int = 20):
    """
    Returns list of rows for a user's orders, newest first.
    Each row: (id, user_id, order_code, status, description, created_at)
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT id, user_id, order_code, status, description, created_at
    FROM orders
    WHERE user_id = ?
    ORDER BY id DESC
    LIMIT ?
    """, (user_id, limit))

    rows = cursor.fetchall()
    conn.close()
    return rows

