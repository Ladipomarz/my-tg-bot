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

            # ✅ Orders now store payment info + expiry
            cur.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                order_code TEXT UNIQUE,
                status TEXT,                 -- pending, paid, completed, cancelled, expired
                description TEXT,
                created_at TIMESTAMP,
                expires_at TIMESTAMP,        -- ✅ 1 hour expiry
                invoice_url TEXT,            -- ✅ store NOWPayments invoice url
                pay_currency TEXT            -- ✅ btc/usdttrc20/etc
            );
            """)

            # useful indexes
            cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);")


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


def create_order(user_id: int, description: str = "", ttl_seconds: int = 3600) -> tuple:
    now = datetime.datetime.utcnow()
    expires_at = now + datetime.timedelta(seconds=int(ttl_seconds))

    with get_connection() as conn:
        with conn.cursor() as cur:
            order_code = _generate_order_code(cur)

            cur.execute("""
                INSERT INTO orders (user_id, order_code, status, description, created_at, expires_at)
                VALUES (%s, %s, 'pending', %s, %s, %s)
                RETURNING id;
            """, (user_id, order_code, description, now, expires_at))

            order_id = cur.fetchone()[0]
            return order_id, order_code


def get_pending_order(user_id: int):
    """
    Returns most recent pending order (may be expired; check with expire_pending_order_if_needed)
    """
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


def expire_pending_order_if_needed(user_id: int):
    """
    If user has a pending order but it's past expires_at, mark it expired.
    Returns updated order row or None.
    """
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT *
                FROM orders
                WHERE user_id = %s AND status = 'pending'
                ORDER BY id DESC
                LIMIT 1;
            """, (user_id,))
            order = cur.fetchone()
            if not order:
                return None

            expires_at = order.get("expires_at")
            now = datetime.datetime.utcnow()

            if expires_at and now >= expires_at:
                cur.execute("""
                    UPDATE orders
                    SET status = 'expired'
                    WHERE id = %s;
                """, (order["id"],))
                conn.commit()

                # re-fetch
                cur.execute("SELECT * FROM orders WHERE id = %s;", (order["id"],))
                return cur.fetchone()

            return order


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


def set_order_payment(order_id: int, *, invoice_url: str, pay_currency: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE orders
                SET invoice_url = %s,
                    pay_currency = %s
                WHERE id = %s;
            """, (invoice_url, pay_currency, order_id))


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


def cleanup_old_orders(hours: int = 24):
    """
    Optional: deletes old cancelled/expired orders older than `hours`.
    You can call this on startup or daily later.
    """
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=int(hours))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM orders
                WHERE status IN ('cancelled', 'expired')
                  AND created_at < %s;
            """, (cutoff,))
