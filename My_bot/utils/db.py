import datetime
import random
import json
import psycopg
from psycopg.rows import dict_row
from io import BytesIO
from psycopg.errors import UndefinedColumn, UndefinedTable
from datetime import datetime, timezone


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
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS balance_usd NUMERIC DEFAULT 0;")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS balance_updated_at TIMESTAMPTZ;")
        conn.commit()


def migrate_orders_schema():
    """Add new columns without breaking existing DB."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # base additions used by your handlers
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;")
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS invoice_url TEXT;")
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS pay_currency TEXT;")
            # wallet stuffs
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS amount_usd NUMERIC;")
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS order_type TEXT;")
            cur.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS wallet_credited BOOLEAN DEFAULT FALSE;")

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
    # Ensure 'users' table is created first
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Create the 'users' table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT UNIQUE
                );
            """)

            # Create the 'orders' table after 'users' table is created
            cur.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id),
                    order_code TEXT UNIQUE,
                    status TEXT,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Create necessary indexes for 'orders'
            cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_order_code ON orders(order_code);")

        conn.commit()

    # Now that the users and orders tables exist, create the wallet_transactions table
    create_wallet_transactions_table()

    migrate_users_schema()
    migrate_orders_schema()


def create_wallet_transactions_table():
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Create the 'wallet_transactions' table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS wallet_transactions (
                    id SERIAL PRIMARY KEY,
                    user_id INT NOT NULL REFERENCES users(id),  -- Reference to the 'id' column in 'users' table
                    order_code VARCHAR(255) UNIQUE,
                    amount_usd DECIMAL(10, 2),
                    status VARCHAR(20) DEFAULT 'pending',  -- Can be 'pending', 'completed', 'cancelled'
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
        


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


def create_order(user_id: int, description: str, ttl_seconds: int = 3600, amount_usd=None, order_type=None):
    """
    Returns: (id, order_code)
    """
    migrate_orders_schema()

    now = datetime.now(timezone.utc)
    expires_at = now + datetime.timedelta(seconds=int(ttl_seconds))

    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            code = _generate_order_code(cur)
            cur.execute("""         
                            INSERT INTO orders (
                                user_id, order_code, status, description,
                                created_at, expires_at,
                                amount_usd, order_type,
                                pay_status, pay_provider, pay_updated_at,
                                delivery_status, delivered_at,
                                delivery_file_id, delivery_filename,
                                status_updated_at, delivery_payload_json,
                                delivered_message_id
                               ) 
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                RETURNING id, order_code;
                                """,
                                
                               (   
                                    user_id, code, "pending", description,
                                    now, expires_at,
                                    amount_usd, order_type,
                                    "pending", None, now,
                                    "not_delivered", None,
                                    None, None,
                                    now, None,
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
            """, (status, datetime.now(timezone.utc), order_id))
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
                WHERE user_id = %s
                  AND status = 'pending'
                  AND (expires_at IS NULL OR expires_at > (NOW() AT TIME ZONE 'utc'))
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
    if not expires_at:
        return pending

    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except Exception:
            return pending

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    if now >= expires_at:
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
    Ensures:
      - service_fetch_status table exists and has row id=1
      - services table exists with the RIGHT constraints to store BOTH sms and voice
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # ---- status table ----
            cur.execute("""
                CREATE TABLE IF NOT EXISTS service_fetch_status (
                    id INT PRIMARY KEY,
                    fetched BOOLEAN NOT NULL DEFAULT FALSE
                );
            """)
            
            cur.execute("""
                INSERT INTO service_fetch_status (id, fetched)
                VALUES (1, FALSE)
                ON CONFLICT (id) DO NOTHING;
            """)
            

            # ---- services table ----
            cur.execute("""
                CREATE TABLE IF NOT EXISTS services (
                    local_code INT UNIQUE NOT NULL,
                    service_name TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_services_local_code ON services(local_code);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_services_capability ON services(capability);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_services_name ON services(service_name);")

            # IMPORTANT: enforce per-capability uniqueness
            # Drop the old unique constraint on service_name if it exists (common auto-name: services_service_name_key)
            cur.execute("ALTER TABLE services DROP CONSTRAINT IF EXISTS services_service_name_key;")

            # Add composite unique constraint (service_name, capability) if not already there
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'services_service_name_capability_key'
                    ) THEN
                        ALTER TABLE services
                        ADD CONSTRAINT services_service_name_capability_key
                        UNIQUE (service_name, capability);
                    END IF;
                END$$;
            """)

        conn.commit()
        
        


# ---------------- FUNCTION TO CHECK FETCH STATUS ----------------        
        
# Function to check if the services have already been fetched
# type: ignore
def has_services_been_fetched() -> bool:
    print("Checking if services have been fetched...")  # Debugging line

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
def store_services_in_db(services):
    """
    Stores BOTH SMS + VOICE as separate rows:
      UNIQUE(service_name, capability)

    Code rules:
      - Existing rows keep their local_code
      - New (service_name, capability) rows get next local_code (sequential)
    """
    if not services:
        print("No services provided to store_services_in_db().")
        return

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Ensure schema exists + constraints are correct
            create_service_fetch_status_table()

            # Start from current max local_code
            cur.execute("SELECT COALESCE(MAX(local_code), 0) FROM services;")
            next_code = int(cur.fetchone()[0]) + 1

            # Deterministic order helps stability (same insert order every run)
            def _cap_value(s):
                cap = getattr(s, "capability", None)
                return cap.value if hasattr(cap, "value") else (str(cap) if cap else "")

            services_sorted = sorted(
                services,
                key=lambda s: ((getattr(s, "service_name", "") or "").lower(), (_cap_value(s) or "").lower()),
            )

            inserted = 0
            updated = 0

            for s in services_sorted:
                name = (getattr(s, "service_name", None) or "").strip()
                if not name:
                    continue

                cap_val = _cap_value(s).strip().lower()
                if not cap_val:
                    # If TextVerified ever returns empty, skip (or you can default to 'sms')
                    continue

                # If row exists for (name, cap) -> keep local_code; update capability text (safe)
                cur.execute(
                    "SELECT local_code FROM services WHERE service_name = %s AND capability = %s;",
                    (name, cap_val),
                )
                row = cur.fetchone()

                if row:
                    # Nothing really to update except being safe
                    cur.execute(
                        "UPDATE services SET capability = %s WHERE service_name = %s AND capability = %s;",
                        (cap_val, name, cap_val),
                    )
                    updated += 1
                    continue

                # Insert new pair (name, cap)
                cur.execute(
                    """
                    INSERT INTO services (local_code, service_name, capability)
                    VALUES (%s, %s, %s);
                    """,
                    (next_code, name, cap_val),
                )
                next_code += 1
                inserted += 1

        conn.commit()

    print(f"✅ Services saved. Inserted new rows: {inserted} | Existing rows seen: {updated}")


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
        
        
        


def get_services_rows(*, capability: str = "sms"):
    """
    Returns list of dicts: [{local_code, service_name, capability}, ...]
    """
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT local_code, service_name, capability
                FROM services
                WHERE LOWER(COALESCE(capability,'')) = LOWER(%s)
                ORDER BY local_code ASC;
                """,
                (capability,),
            )
            return cur.fetchall()

def build_services_txt_bytes(*, capability: str = "sms") -> tuple[bytes, str]:
    """
    Builds a text file content from DB services, returns (bytes, filename)
    """
    rows = get_services_rows(capability=capability)

    lines = []

    # First, add "General service" as the first line (with bold in the Telegram caption)
    lines.append("General service: This service is for cases where the provider is not listed in the TextVerified catalog.")
    lines.append("")  # Empty line for spacing

    # Now loop through all the rows and add them to the list
    for r in rows:
        # If service is 'servicenotlisted' or 'general', display it as "General service"
        display_name = "General service" if r['service_name'].strip().lower() in {"servicenotlisted", "general"} else r['service_name']

        # Add the product ID and service, with the separator after each
        lines.append(f"Product ID: {r['local_code']}")
        lines.append(f"Service: {display_name}")
        lines.append(f"______________________\n")

    # Join all the lines into the final content
    content = "\n".join(lines) + "\n"
    filename = f"services_{capability.lower()}.txt"

    # Return the content as bytes and the filename
    return content.encode("utf-8"), filename




def get_services_for_export(*, capability: str | None = "sms") -> list[tuple[str, str]]:
    """
    Returns list of (code, service_name) from DB.
    Tries (local_code, capability) schema first, falls back to (product_id) schema.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Try new schema: local_code + capability
            try:
                if capability:
                    cur.execute(
                        """
                        SELECT local_code, service_name
                        FROM services
                        WHERE capability = %s
                        ORDER BY local_code ASC;
                        """,
                        (capability,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT local_code, service_name
                        FROM services
                        ORDER BY local_code ASC;
                        """
                    )
                rows = cur.fetchall()
                return [(str(r[0]).zfill(4), r[1]) for r in rows]
            except (UndefinedColumn, UndefinedTable):
                pass

            # Fallback old schema: product_id + service_name
            cur.execute(
                """
                SELECT product_id, service_name
                FROM services
                ORDER BY product_id ASC;
                """
            )
            rows = cur.fetchall()
            # old codes are ints; still format as 4-digit for display consistency
            return [(str(r[0]).zfill(4), r[1]) for r in rows]


def get_service_name_by_code(code: str) -> str | None:
    """
    Looks up service_name from DB by 4-digit code.
    Converts 4-digit code to int and queries the local_code in the services table.
    """
    code = (code or "").strip()

    # Ensure the code is valid (either 3 or 4 digits)
    if not code.isdigit() or len(code) not in (3, 4):
        return None

    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                # Query by local_code (after converting to int)
                cur.execute(
                    "SELECT service_name FROM services WHERE local_code = %s LIMIT 1;",
                    (int(code),),
                )
                row = cur.fetchone()
                if row:
                    return row[0]
            except Exception as e:
                print(f"Error querying database: {e}")
                return None
    return None

                 

def get_user_balance_usd(user_id: int) -> float:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(balance_usd, 0) FROM users WHERE user_id=%s", (user_id,))
            row = cur.fetchone()
            return float(row[0] if row else 0)

def add_user_balance_usd(user_id: int, amount_usd: float) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET balance_usd = COALESCE(balance_usd, 0) + %s,
                    balance_updated_at = NOW()
                WHERE user_id = %s
                """,
                (amount_usd, user_id),
            )
        conn.commit()

def mark_order_wallet_credited(order_code: str) -> None:
    migrate_orders_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE orders SET wallet_credited = TRUE WHERE order_code = %s",
                (order_code,),
            )
        conn.commit()

def get_last_wallet_transactions(user_id: int, limit: int = 5):
    migrate_orders_schema()
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT order_code, amount_usd, pay_status, status, created_at
                FROM orders
                WHERE user_id=%s
                  AND (order_type='wallet_topup' OR LEFT(description, 12) = 'WALLET_TOPUP:')
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
            return cur.fetchall()
