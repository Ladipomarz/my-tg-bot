import datetime
import random
import psycopg
from psycopg.rows import dict_row
from config import DATABASE_URL


def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set in environment variables")
    return psycopg.connect(DATABASE_URL)


def create_tables():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                first_name TEXT,
                username TEXT,
                is_admin INTEGER DEFAULT 0
            );
            """)

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


# ---------- Users helpers ----------

def add_user(user_id, first_name, username, is_admin=0):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, first_name, username, is_admin)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING;
            """, (user_id, first_name, username, is_admin))


def get_user(user_id):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s;", (user_id,))
            return cur.fetchone()


# ---------- Orders helpers ----------

def _generate_order_code(cur) -> str:
    while True:
        num = random.randint(100_000_000, 999_999_999)
        code = f"{num}#"
        cur.execute("SELECT 1 FROM orders WHERE order_code = %s;", (code,))
        if not cur.fetchone():
            return code


def create_order(user_id: int, description: str = "") -> tuple:
    created_at = datetime.datetime.utcnow()

    with get_connection() as conn:
        with conn.cursor() as cur:
            order_code = _generate_order_code(cur)

            cur.execute("""
                INSERT INTO orders (user_id, order_code, status, description, created_at)
                VALUES (%s, %s, 'pending', %s, %s)
                RETURNING id;
            """, (user_id, order_code, description, created_at))

            order_id = cur.fetchone()[0]
            return order_id, order_code


def get_pending_order(user_id: int):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT *
                FROM orders
                WHERE user_id = %s AND status = 'pending'
                ORDER BY id DESC
                LIMIT 1;
            """, (user_id,))
            return cur.fetchone()


def update_order_status(order_id: int, status: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE orders
                SET status = %s
                WHERE id = %s;
            """, (status, order_id))


def set_order_description(order_id: int, description: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE orders
                SET description = %s
                WHERE id = %s;
            """, (description, order_id))


def get_orders_for_user(user_id: int, limit: int = 20):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT *
                FROM orders
                WHERE user_id = %s
                ORDER BY id DESC
                LIMIT %s;
            """, (user_id, limit))
            return cur.fetchall()
