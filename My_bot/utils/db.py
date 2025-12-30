import datetime
import random
import psycopg
from psycopg.rows import dict_row
from My_bot.config import DATABASE_URL


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

            # ✅ Payment tracking (Plisio + future providers)
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_provider TEXT;")
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_txn_id TEXT;")
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_status TEXT;")
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_updated_at TIMESTAMP;")
        conn.commit()


def create_tables():
    with get_connection() as conn:
        with conn.cursor() as cur:
            # users table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                user_id BIGINT UNIQUE,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                created_at TIMESTAMP
            );
            """)

            # orders table
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

    # run migrations after base tables exist
    migrate_orders_schema()


def upsert_user(user_id, username=None, first_name=None, last_name=None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, username, first_name, last_name, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name;
            """, (user_id, username, first_name, last_name, datetime.datetime.utcnow()))
        conn.commit()


def get_user(user_id):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s;", (user_id,))
            return cur.fetchone()


# ---------- Orders helpers ----------

def _generate_order_code(cur) -> str:
    while True:
        n = random.randint(100000, 999999)
        code = f"ORD-{n}"
        cur.execute("SELECT 1 FROM orders WHERE order_code = %s;", (code,))
        if not cur.fetchone():
            return code


def create_order(user_id: int, description: str, status: str = "pending"):
    """
    Creates an order for a user and returns it as dict.
    """
    migrate_orders_schema()
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            order_code = _generate_order_code(cur)
            cur.execute("""
                INSERT INTO orders (user_id, order_code, status, description, created_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *;
            """, (user_id, order_code, status, description, datetime.datetime.utcnow()))
            order = cur.fetchone()
        conn.commit()
    return order


def set_order_status(order_id: int, status: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE orders SET status = %s WHERE id = %s;", (status, order_id))
        conn.commit()


def cancel_pending_order(user_id: int):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE orders
                SET status = 'cancelled'
                WHERE user_id = %s AND status = 'pending';
            """, (user_id,))
        conn.commit()


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
    """
    If a user's pending order has expired, mark it expired and return it.
    Otherwise return the current pending order (or None).
    """
    migrate_orders_schema()
    pending = get_pending_order(user_id)
    if not pending:
        return None

    expires_at = pending.get("expires_at")
    if expires_at and datetime.datetime.utcnow() > expires_at:
        set_order_status(pending["id"], "expired")
        pending["status"] = "expired"
        return pending

    return pending


def set_order_expiry(order_id: int, minutes: int = 15):
    migrate_orders_schema()
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=int(minutes))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE orders SET expires_at = %s WHERE id = %s;", (expires_at, order_id))
        conn.commit()


def set_order_payment(
    order_id: int,
    *,
    invoice_url: str,
    pay_currency: str,
    pay_provider: str = "plisio",
    pay_txn_id: str | None = None,
    pay_status: str = "pending",
):
    """Attach payment metadata to an order."""
    migrate_orders_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE orders
                SET invoice_url = %s,
                    pay_currency = %s,
                    pay_provider = %s,
                    pay_txn_id = %s,
                    pay_status = %s,
                    pay_updated_at = %s
                WHERE id = %s;
                """,
                (
                    invoice_url,
                    pay_currency,
                    pay_provider,
                    pay_txn_id,
                    pay_status,
                    datetime.datetime.utcnow(),
                    order_id,
                ),
            )
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


def get_order_by_code(order_code: str):
    migrate_orders_schema()
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM orders WHERE order_code = %s LIMIT 1;", (order_code,))
            return cur.fetchone()


def update_payment_status_by_order_code(
    order_code: str,
    *,
    pay_status: str,
    pay_txn_id: str | None = None,
):
    """Update payment status for an order (called by Plisio webhook)."""
    migrate_orders_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE orders
                SET pay_status = %s,
                    pay_txn_id = COALESCE(%s, pay_txn_id),
                    pay_updated_at = %s
                WHERE order_code = %s;
                """,
                (
                    pay_status,
                    pay_txn_id,
                    datetime.datetime.utcnow(),
                    order_code,
                ),
            )
        conn.commit()


def list_all_orders(limit: int = 100):
    migrate_orders_schema()
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT *
                FROM orders
                ORDER BY id DESC
                LIMIT %s;
            """, (limit,))
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
