import datetime
import random
import json
import psycopg
from psycopg.rows import dict_row

from config import DATABASE_URL

def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg.connect(DATABASE_URL)        
        

def test_connection():
    try:
        conn = get_connection()
        print("Database connection successful!")
        conn.close()
    except Exception as e:
        print(f"Error connecting to database: {e}")

test_connection()



# ---------------- MIGRATIONS ----------------

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

            # payment tracking
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_provider TEXT;")
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_txn_id TEXT;")
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_status TEXT;")
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_updated_at TIMESTAMP;")

            # fulfillment / delivery tracking
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_status TEXT;")
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMP;")

            # delivered file reference for re-send
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_file_id TEXT;")
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_filename TEXT;")

            # hide cancelled/expired after 1 minute
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS status_updated_at TIMESTAMP;")

            # ✅ store admin delivery fields as JSON (for view/edit/re-deliver)
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_payload_json TEXT;")

            # ✅ store message_id of the delivery doc sent to user (so you can delete it later)
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivered_message_id BIGINT;")

            # ✅ archive table for old delivery files (soft-delete / audit trail)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS order_delivery_files (
                    id SERIAL PRIMARY KEY,
                    order_code TEXT,
                    file_id TEXT,
                    filename TEXT,
                    message_id BIGINT,
                    created_at TIMESTAMP
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_odf_order_code ON order_delivery_files(order_code);")

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
    # backwards compatible wrapper
    return upsert_user(user_id, username=username, first_name=first_name)


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
    Returns: (id, order_code)
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
                    status_updated_at,
                    delivery_payload_json,
                    delivered_message_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                now,
                None,
                None,
            ))
            row = cur.fetchone()
        conn.commit()

    return row["id"], row["order_code"]


def set_order_status(order_id: int, status: str):
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


def update_order_status(order_id: int, status: str):
    # backwards compatible alias
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

    cutoff = datetime.datetime.utcnow() - datetime.timedelta(
        seconds=int(hide_cancelled_expired_after_seconds)
    )

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


# ---------------- DELIVERY FILES ----------------

def save_delivery_file_by_code(order_code: str, *, file_id: str, filename: str):
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


def get_delivery_file_by_code(order_code: str):
    migrate_orders_schema()
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT delivery_file_id, delivery_filename
                FROM orders
                WHERE order_code = %s
                LIMIT 1;
            """, (order_code,))
            return cur.fetchone()


def archive_previous_delivery_file(order_code: str):
    """
    Saves current (delivery_file_id, delivery_filename, delivered_message_id) into archive table
    BEFORE you overwrite it with a corrected delivery.
    """
    migrate_orders_schema()
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT delivery_file_id, delivery_filename, delivered_message_id
                FROM orders
                WHERE order_code = %s
                LIMIT 1;
            """, (order_code,))
            row = cur.fetchone()

            if not row:
                conn.commit()
                return

            file_id = (row.get("delivery_file_id") or "").strip()
            filename = (row.get("delivery_filename") or "").strip()
            message_id = row.get("delivered_message_id")

            if not file_id:
                conn.commit()
                return

            cur.execute("""
                INSERT INTO order_delivery_files(order_code, file_id, filename, message_id, created_at)
                VALUES (%s, %s, %s, %s, %s);
            """, (order_code, file_id, filename or None, message_id, datetime.datetime.utcnow()))

        conn.commit()


def get_current_delivery_message_id(order_code: str) -> int | None:
    migrate_orders_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT delivered_message_id
                FROM orders
                WHERE order_code = %s
                LIMIT 1;
            """, (order_code,))
            row = cur.fetchone()
            if not row:
                return None
            return row[0]


# ---------------- DELIVERY META (FIELDS) ----------------

def save_delivery_meta_by_code(
    order_code: str,
    *,
    payload: dict,
    delivered_message_id: int | None = None,
):
    """
    Store admin inputs so you can view/edit/redeliver later.
    """
    migrate_orders_schema()
    payload_json = json.dumps(payload)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE orders
                SET delivery_payload_json = %s,
                    delivered_message_id = COALESCE(%s, delivered_message_id)
                WHERE order_code = %s;
            """, (payload_json, delivered_message_id, order_code))
        conn.commit()


def get_delivery_payload_by_code(order_code: str) -> dict | None:
    migrate_orders_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT delivery_payload_json
                FROM orders
                WHERE order_code = %s
                LIMIT 1;
            """, (order_code,))
            row = cur.fetchone()

    if not row:
        return None

    raw = row[0]
    if not raw:
        return None

    try:
        return json.loads(raw)
    except Exception:
        return None


# ---------------- LOOKUPS ----------------

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
        

def create_service_fetch_status_table():
    """
    Creates the service_fetch_status table if it doesn't exist.
    This function ensures that the table is available on deployment.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS service_fetch_status (
                id SERIAL PRIMARY KEY,
                fetched BOOLEAN DEFAULT FALSE
            );
        """)

        conn.commit()
        cursor.close()
        conn.close()

        print("Service fetch status table created successfully (if it didn't exist).")
    except Exception as e:
        print(f"Error creating service_fetch_status table: {e}")

# ---------------- FUNCTION TO CHECK FETCH STATUS ----------------        
        
# Function to check if the services have already been fetched
# type: ignore
def has_services_been_fetched() -> bool:
    """
    Checks if the service list has already been fetched and stored in the database.
    """
    try:
        conn = get_connection()  # Ensure this returns a valid connection
        cursor = conn.cursor()

        # Check the service_fetch_status table to see if it has already been fetched
        cursor.execute("SELECT fetched FROM service_fetch_status WHERE id = 1;")
        result = cursor.fetchone()

        cursor.close()
        conn.close()

        return result and result[0]  # Returns True if the service list has been fetched
    except Exception as e:
        print(f"Error checking fetch status: {e}")
        return False  # Return False if any error occurs, so services will be fetched

# ---------------- STORE SERVICES ----------------


# Function to store services in the database
async def store_services_in_db(services):
    """
    This function takes the fetched services and stores them in the database.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Create the services table if it doesn't exist
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS services (
                product_id INT PRIMARY KEY,
                service_name VARCHAR(255)
            );
        """)
    except Exception as e:
        print(f"Error creating table: {e}")
        return  # If table creation fails, exit early

    used_ids = set()

    # Loop through services and assign random 3-digit IDs
    for service in services:
        try:
            while True:
                product_id = random.randint(100, 999)
                if product_id not in used_ids:
                    used_ids.add(product_id)
                    break

            service_name = service.service_name  # Assuming `service_name` is an attribute of the Service object

            cursor.execute(
                "INSERT INTO services (product_id, service_name) VALUES (%s, %s) ON CONFLICT (product_id) DO NOTHING",
                (product_id, service_name)
            )

        except Exception as e:
            print(f"Error inserting service {service_name}: {e}")
            continue  # If one service insertion fails, continue with the next service

    try:
        conn.commit()
        print("Services stored successfully.")
    except Exception as e:
        print(f"Error committing transaction: {e}")
    finally:
        cursor.close()
        conn.close()

# ---------------- MARK FETCHED STATUS ----------------

# Function to mark the service list as fetched
def save_service_fetch_status():
    """
    Marks the service list as fetched in the service_fetch_status table.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Insert or update the fetch status to True (we use ON CONFLICT to avoid duplicates)
        cursor.execute("INSERT INTO service_fetch_status (id, fetched) VALUES (1, TRUE) ON CONFLICT (id) DO UPDATE SET fetched = TRUE;")

        conn.commit()
        cursor.close()
        conn.close()
        print("Service fetch status has been updated.")
    except Exception as e:
        print(f"Error saving fetch status: {e}")
    
