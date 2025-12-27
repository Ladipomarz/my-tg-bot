import datetime
import random
import psycopg
from psycopg.rows import dict_row
from config import DATABASE_URL


def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set in environment variables")
    return psycopg.connect(DATABASE_URL)


# ✅ Always keep migrations OUTSIDE create_tables (clean + reusable)
def migrate_orders_schema():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;")
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS invoice_url TEXT;")
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_currency TEXT;")
        conn.commit()


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

            # Base table
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

            # indexes
            cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);")

        conn.commit()

    # ✅ Run migrations after base table exists
    migrate_orders_schema()


# ---------- Users helpers ----------

def add_user(user_id, first_name, username, is_admin=0):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, first_name, username, is_admin)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING;
            """, (user_id, first_name, username, is_admin))
        conn.commit()


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
    # ✅ GUARANTEE migrations even if create_tables didn't run (or old DB)
    migrate_orders_schema()

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
        conn.commit()
        return order_id, order_code


def get_pending_order(user_id: int):
    migrate_orders_schema()
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
    migrate_orders_schema()
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
        conn.commit()


def set_order_description(order_id: int, description: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE orders
                SET description = %s
                WHERE id = %s;
            """, (description, order_id))
        conn.commit()


def set_order_payment(order_id: int, *, invoice_url: str, pay_currency: str):
    migrate_orders_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE orders
                SET invoice_url = %s,
                    pay_currency = %s
                WHERE id = %s;
            """, (invoice_url, pay_currency, order_id))
        conn.commit()


def get_orders_for_user(user_id: int, limit: int = 20):
    migrate_orders_schema()
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
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=int(hours))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM orders
                WHERE status IN ('cancelled', 'expired')
                  AND created_at < %s;
            """, (cutoff,))
        conn.commit()

