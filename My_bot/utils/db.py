import psycopg2
import datetime
import random
from psycopg2.extras import RealDictCursor
from config import DATABASE_URL


def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set in environment variables")
    return psycopg2.connect(DATABASE_URL)


def create_tables():
    conn = get_connection()
    cur = conn.cursor()

    # Users table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        first_name TEXT,
        username TEXT,
        is_admin INTEGER DEFAULT 0
    );
    """)

    # Orders table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        order_code TEXT UNIQUE,
        status TEXT,
        description TEXT,
        created_at TIMESTAMP
    );
    """)

    conn.commit()
    cur.close()
    conn.close()


# ---------- Users helpers ----------

def add_user(user_id, first_name, username, is_admin=0):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO users (user_id, first_name, username, is_admin)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (user_id) DO NOTHING;
    """, (user_id, first_name, username, is_admin))

    conn.commit()
    cur.close()
    conn.close()


def get_user(user_id):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT * FROM users WHERE user_id = %s;", (user_id,))
    user = cur.fetchone()

    cur.close()
    conn.close()
    return user


# ---------- Orders helpers ----------

def _generate_order_code(cur) -> str:
    while True:
        num = random.randint(100_000_000, 999_999_999)
        code = f"{num}#"
        cur.execute("SELECT 1 FROM orders WHERE order_code = %s;", (code,))
        if not cur.fetchone():
            return code


def create_order(user_id: int, description: str = "") -> tuple:
    conn = get_connection()
    cur = conn.cursor()

    order_code = _generate_order_code(cur)
    created_at = datetime.datetime.utcnow()

    cur.execute("""
    INSERT INTO orders (user_id, order_code, status, description, created_at)
    VALUES (%s, %s, 'pending', %s, %s)
    RETURNING id;
    """, (user_id, order_code, description, created_at))

    order_id = cur.fetchone()[0]
    conn.commit()

    cur.close()
    conn.close()
    return order_id, order_code


def get_pending_order(user_id: int):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
    SELECT *
    FROM orders
    WHERE user_id = %s AND status = 'pending'
    ORDER BY id DESC
    LIMIT 1;
    """, (user_id,))

    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def update_order_status(order_id: int, status: str):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    UPDATE orders
    SET status = %s
    WHERE id = %s;
    """, (status, order_id))

    conn.commit()
    cur.close()
    conn.close()


def set_order_description(order_id: int, description: str):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    UPDATE orders
    SET description = %s
    WHERE id = %s;
    """, (description, order_id))

    conn.commit()
    cur.close()
    conn.close()


def get_orders_for_user(user_id: int, limit: int = 20):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
    SELECT *
    FROM orders
    WHERE user_id = %s
    ORDER BY id DESC
    LIMIT %s;
    """, (user_id, limit))

    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

