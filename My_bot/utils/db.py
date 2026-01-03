import datetime
import random
import psycopg
from psycopg.rows import dict_row

from config import DATABASE_URL


def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg.connect(DATABASE_URL)


def migrate_users_schema():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT;")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT;")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP;")
        conn.commit()


def migrate_orders_schema():
    """Add new columns without breaking existing DB."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # base additions used by your handlers
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;")
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS invoice_url TEXT;")
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_currency TEXT;")

            # payment tracking for Plisio (and future providers)
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_provider TEXT;")
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_txn_id TEXT;")
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_status TEXT;")
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_updated_at TIMESTAMP;")

            # ✅ fulfillment / delivery tracking (manual step after paid)
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_status TEXT;")
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMP;")

            # ✅ store delivered file reference for re-send later
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_file_id TEXT;")
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_filename TEXT;")

            # ✅ for "hide cancelled/expired after 1 minute"
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS status_updated_at TIMESTAMP;")
        conn.commit()


def create_tables():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                user_id BIGINT UNIQUE
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

            cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_order_code ON orders(order_code);")

        conn.commit()

    migrate_users_schema()
    migrate_orders_schema()


# ---------------- USERS ----------------

def upsert_user(
    user_id: int,
    username: str | None = None,
    first_name: str | None = None,
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, username, first_name, created_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name;
            """, (user_id, username, first_name, datetime.datetime.utcnow()))
        conn.commit()


def add_user(user_id: int, first_name: str | None = None, username: str | None = None):
    """
    Backwards compatible wrapper.
    Old code: add_user(user.id, user.first_name, user.username)
    """
    return upsert_user(
        user_id,
        username=username,
        first_name=first_name,
    )


def get_user(user_id: int):
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s;", (user_id,))
            return cur.fetchone()


# ---------------- ORDERS ----------------

def _generate_order_code(cur) -> str:
    while True:
        n = random.randint(100000, 999999)
        code = f"ORD-{n}"
        cur.execute("SELECT 1 FROM orders WHERE order_code = %s;", (code,))
        if not cur.fetchone():
            return code


def create_order(user_id: int, description: str, ttl_seconds: int = 3600):
    """
    Your handlers expect:
      order_id, order_code = create_order(..., ttl_seconds=3600)

    So we return (id, order_code).
    """
    migrate_orders_schema()

    now = datetime.datetime.utcnow()
    expires_at = now + datetime.timedelta(seconds=int(ttl_seconds))

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            code = _generate_order_code(cur)
            cur.execute("""
                INSERT INTO orders (
                    user_id,
                    order_code,
                    status,
                    description,
                    created_at,
                    expires_at,
                    pay_status,
                    pay_provider,
                    pay_updated_at,
                    delivery_status,
                    delivered_at,
                    delivery_file_id,
                    delivery_filename,
                    status_updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, order_code;
            """, (
                user_id,
                code,
                "pending",
                description,
                now,
                expires_at,
                "pending",
                None,
                now,
                "not_delivered",
                None,
                None,
                None,
                now,  # status_updated_at
            ))
            row = cur.fetchone()
        conn.commit()

    return row["id"], row["order_code"]


def set_order_status(order_id: int, status: str):
    """Updates status and status_updated_at (needed for hide-after-1-minute)."""
    migrate_orders_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE orders
                SET status = %s,
                    status_updated_at = %s
                WHERE id = %s;
            """, (status, datetime.datetime.utcnow(), order_id))
        conn.commit()


# ✅ Backwards-compatible alias (your handlers import update_order_status)
def update_order_status(order_id: int, status: str):
    return set_order_status(order_id, status)


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
    pending = get_pending_order(user_id)
    if not pending:
        return None

    expires_at = pending.get("expires_at")
    if expires_at and datetime.datetime.utcnow() > expires_at:
        set_order_status(pending["id"], "expired")
        pending["status"] = "expired"
        return pending

    return pending


def get_orders_for_user(
    user_id: int,
    limit: int = 20,
    offset: int = 0,
    *,
    hide_cancelled_expired_after_seconds: int = 60,
    include_archived: bool = False,
):
    """
    Paginated orders.
    - include_archived=False hides cancelled/expired after N seconds (default 60s).
    - include_archived=True returns everything.
    """
    migrate_orders_schema()

    cutoff = datetime.datetime.utcnow() - datetime.timedelta(seconds=int(hide_cancelled_expired_after_seconds))

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            if include_archived:
                cur.execute("""
                    SELECT *
                    FROM orders
                    WHERE user_id = %s
                    ORDER BY id DESC
                    LIMIT %s OFFSET %s;
                """, (user_id, limit, offset))
                return cur.fetchall()

            # hide cancelled/expired once they are older than cutoff
            cur.execute("""
                SELECT *
                FROM orders
                WHERE user_id = %s
                  AND NOT (
                        status IN ('cancelled', 'expired')
                        AND COALESCE(status_updated_at, created_at, NOW()) < %s
                  )
                ORDER BY id DESC
                LIMIT %s OFFSET %s;
            """, (user_id, cutoff, limit, offset))
            return cur.fetchall()


def set_order_payment(
    order_id: int,
    *,
    invoice_url: str,
    pay_currency: str,
    pay_provider: str = "plisio",
    pay_txn_id: str | None = None,
    pay_status: str = "pending",
):
    migrate_orders_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE orders
                SET invoice_url = %s,
                    pay_currency = %s,
                    pay_provider = %s,
                    pay_txn_id = %s,
                    pay_status = %s,
                    pay_updated_at = %s
                WHERE id = %s;
            """, (
                invoice_url,
                pay_currency,
                pay_provider,
                pay_txn_id,
                pay_status,
                datetime.datetime.utcnow(),
                order_id
            ))
        conn.commit()


def update_payment_status_by_order_code(
    order_code: str,
    *,
    pay_status: str,
    pay_txn_id: str | None = None
):
    migrate_orders_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE orders
                SET pay_status = %s,
                    pay_txn_id = COALESCE(%s, pay_txn_id),
                    pay_updated_at = %s
                WHERE order_code = %s;
            """, (pay_status, pay_txn_id, datetime.datetime.utcnow(), order_code))
        conn.commit()


def set_delivery_status(order_id: int, delivery_status: str):
    """
    delivery_status:
      - not_delivered
      - delivered
    """
    migrate_orders_schema()
    delivered_at = datetime.datetime.utcnow() if delivery_status == "delivered" else None

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE orders
                SET delivery_status = %s,
                    delivered_at = %s
                WHERE id = %s;
            """, (delivery_status, delivered_at, order_id))
        conn.commit()


def mark_order_delivered(order_code: str):
    """Marks delivered. File id/name are saved separately via save_delivery_file_by_code()."""
    migrate_orders_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE orders
                SET delivery_status = 'delivered',
                    delivered_at = %s
                WHERE order_code = %s;
            """, (datetime.datetime.utcnow(), order_code))
        conn.commit()


def save_delivery_file_by_code(order_code: str, *, file_id: str, filename: str = "service.txt"):
    """Save Telegram document file_id so user can re-request file later."""
    migrate_orders_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE orders
                SET delivery_file_id = %s,
                    delivery_filename = %s
                WHERE order_code = %s;
            """, (file_id, filename, order_code))
        conn.commit()


def get_order_by_code(order_code: str):
    migrate_orders_schema()
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM orders WHERE order_code = %s LIMIT 1;", (order_code,))
            return cur.fetchone()


def get_paid_orders_for_admin(limit: int = 10, offset: int = 0):
    """
    Orders ready to fulfill:
    pay_status in (detected, paid) AND not delivered yet.
    """
    migrate_orders_schema()
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT *
                FROM orders
                WHERE COALESCE(pay_status,'') IN ('detected','paid')
                  AND COALESCE(delivery_status,'not_delivered') <> 'delivered'
                ORDER BY COALESCE(pay_updated_at, created_at, NOW()) DESC, id DESC
                LIMIT %s OFFSET %s;
            """, (limit, offset))
            return cur.fetchall()


def get_delivered_orders_for_admin(limit: int = 10, offset: int = 0):
    """
    Delivered orders list for admin.
    """
    migrate_orders_schema()
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT *
                FROM orders
                WHERE COALESCE(delivery_status,'') = 'delivered'
                ORDER BY COALESCE(delivered_at, created_at, NOW()) DESC, id DESC
                LIMIT %s OFFSET %s;
            """, (limit, offset))
            return cur.fetchall()
