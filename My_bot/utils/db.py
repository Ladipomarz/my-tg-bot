import datetime
import random
import os
import json
import psycopg
from psycopg.rows import dict_row
from io import BytesIO
from psycopg.errors import UndefinedColumn, UndefinedTable
import logging
from config import DATABASE_URL

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)





def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg.connect(DATABASE_URL) 


async def fix_db_sequence(update, context):
    """Temporary command to resync the PostgreSQL ID counter."""
    # This SQL command fast-forwards the sequence to match the highest ID in the table
    query = "SELECT setval(pg_get_serial_sequence('active_rentals', 'id'), coalesce(max(id),0) + 1, false) FROM active_rentals;"
    
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
            conn.commit()
        await update.message.reply_text("✅ Database ID counter successfully resynced!")
    except Exception as e:
        await update.message.reply_text(f"💥 Error fixing sequence: {e}")


# ---------------- MIGRATIONS ----------------

def migrate_users_schema():
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Ensure core columns exist
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS user_id BIGINT;")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT;")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT;")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP;")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS balance_usd NUMERIC DEFAULT 0;")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS balance_updated_at TIMESTAMP;")

            # ✅ Ensure user_id is unique so ON CONFLICT (user_id) works
            cur.execute("""
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'users_user_id_key'
    ) THEN
        ALTER TABLE users ADD CONSTRAINT users_user_id_key UNIQUE (user_id);
    END IF;
END $$;
""")
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
    with get_connection() as conn:
        with conn.cursor() as cur:
            # 1. Create the 'users' table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT UNIQUE
                );
            """)

            # 2. Create the 'orders' table
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
            
            # 3. Create the 'active_rentals' table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS active_rentals (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id),
                    rental_id TEXT UNIQUE,
                    phone_number TEXT,
                    service_name TEXT,
                    always_on BOOLEAN DEFAULT FALSE,
                    is_renewable BOOLEAN DEFAULT FALSE,
                    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'expired', 'cancelled')),
                    expiration_time TIMESTAMP WITH TIME ZONE
                );
            """)

            # Create necessary indexes for 'active_rentals'
            cur.execute("CREATE INDEX IF NOT EXISTS idx_active_rentals_user_id ON active_rentals(user_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_active_rentals_status ON active_rentals(status);")

        # Lock all the changes into PostgreSQL
        conn.commit()
        print("✅ Database tables verified and created successfully.")
        
        
def extend_rental_timer(rental_id: str, days_to_add: int):
    """Adds days to an active rental's expiration and resets the 6h reminder."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE active_rentals 
                SET expiration_time = expiration_time + INTERVAL '%s days',
                    reminder_6h_sent = FALSE 
                WHERE rental_id = %s
            """, (days_to_add, rental_id))
        conn.commit()        

def save_active_rental(user_id: int, rental_id: str, phone_number: str, service_name: str, always_on: bool, is_renewable: bool, days_to_expire: int):
    """Locks the purchased rental number to the Telegram user in the database."""
    
    # Calculate the exact expiration timestamp
    expiration_date = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days_to_expire)
    
    query = """
        INSERT INTO active_rentals 
        (user_id, rental_id, phone_number, service_name, always_on, is_renewable, status, expiration_time)
        VALUES (%s, %s, %s, %s, %s, %s, 'active', %s)
    """
    
    try:
        # Using your exact connection style
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query, 
                    (user_id, rental_id, phone_number, service_name, always_on, is_renewable, expiration_date)
                )
            conn.commit()  # Lock it into the database
            print(f"✅ Saved Rental {phone_number} to DB for User {user_id}")
    except Exception as e:
        print(f"💥 Database Insert Error: {e}")        


    # Now that the users and orders tables exist, create the wallet_transactions table
    create_wallet_transactions_table()

    migrate_users_schema()
    migrate_orders_schema()
    
    
    
        
        
# Run this once or add to your startup script
def update_service_capabilities():
    with get_connection() as conn:
        with conn.cursor() as cur:
            # This ensures your 'capability' column can accept the 'rental' string
            # If you are using a Check Constraint, you might need to update it.
            cur.execute("SELECT DISTINCT capability FROM services;")
            print(f"Current capabilities: {cur.fetchall()}")        


def log_rental_purchase(user_id, phone, ext_id, service, order_code):
    """
    Saves the successful rental to the DB so you can 
    show it in the 'My Numbers' menu later.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Set expiry to 24 hours from now by default
            expires_at = datetime.datetime.now() + datetime.timedelta(days=1)
            
            cur.execute("""
                INSERT INTO rentals (user_id, phone_number, external_rental_id, service_name, order_code, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (user_id, phone, ext_id, service, order_code, expires_at))
        conn.commit()

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

    now = datetime.datetime.utcnow()
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

    # Parse string timestamps safely
    if isinstance(expires_at, str):
        try:
            # Handles "2026-01-28T12:34:56Z" and "+00:00" forms
            s = expires_at.strip().replace("Z", "+00:00")
            expires_at = datetime.datetime.fromisoformat(s)
        except Exception:
            return pending

    # If it's timezone-aware, convert to naive UTC for comparison with utcnow()
    if isinstance(expires_at, datetime.datetime) and expires_at.tzinfo is not None:
        expires_at = expires_at.astimezone(datetime.timezone.utc).replace(tzinfo=None)

    now = datetime.datetime.utcnow()

    if isinstance(expires_at, datetime.datetime) and now >= expires_at:
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
                      AND NOT(
                        order_type='wallet_topup'
                        OR LEFT(COALESCE(description, ''), 12) = 'WALLET_TOPUP:'

                      )
                    ORDER BY id DESC
                    LIMIT %s OFFSET %s;
                """, (user_id, limit, offset))
                return cur.fetchall()

            cur.execute("""
                SELECT *
                FROM orders
                WHERE user_id = %s
                  AND NOT (
                    order_type = 'wallet_topup'
                    OR LEFT(COALESCE(description, ''), 12) = 'WALLET_TOPUP:'
                  )
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
            
            # ✅ NEW: Create the totally separate rental_services table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS rental_services (
                    local_code INT UNIQUE NOT NULL,
                    service_name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_rental_services_local_code ON rental_services(local_code);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_rental_services_name ON rental_services(service_name);")
            cur.execute("ALTER TABLE rental_services DROP CONSTRAINT IF EXISTS rental_services_service_name_key;")
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'rental_services_service_name_key'
                    ) THEN
                        ALTER TABLE rental_services
                        ADD CONSTRAINT rental_services_service_name_key
                        UNIQUE (service_name);
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
    
    
    
    
def store_rental_services_in_db(rental_services):
    """
    Stores ONLY rental services in the isolated rental_services table.
    """
    if not rental_services:
        print("No rental services provided.")
        return

    with get_connection() as conn:
        with conn.cursor() as cur:
            # We will start rental codes at 5000. 
            # This is a cool trick: if a user types a code starting with 0, 1, or 2, 
            # the bot instantly knows they accidentally used the One-Time list!
            cur.execute("SELECT COALESCE(MAX(local_code), 4999) FROM rental_services;")
            next_code = int(cur.fetchone()[0]) + 1

            inserted = 0
            updated = 0

            for s in rental_services:
                name = (getattr(s, "service_name", None) or "").strip()
                if not name:
                    continue

                # Check if it already exists
                cur.execute("SELECT local_code FROM rental_services WHERE service_name = %s;", (name,))
                if cur.fetchone():
                    updated += 1
                    continue

                # Insert new rental service
                cur.execute(
                    "INSERT INTO rental_services (local_code, service_name) VALUES (%s, %s);",
                    (next_code, name),
                )
                next_code += 1
                inserted += 1

        conn.commit()
    print(f"✅ Rental Services saved. Inserted: {inserted} | Existing: {updated}")


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




def get_services_for_export(*, capability: str = "sms") -> list[tuple[str, str]]:
    """
    Returns list of (code, service_name) from DB.
    Tries (local_code, capability) schema first, falls back to (product_id) schema.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            
            logger.debug(f"Fetching services for capability: {capability}")

            # Ensure the capability is not None and handle the default
            capability = capability.strip().lower() if capability else "sms"
            logger.debug(f"Normalized capability to: '{capability}'")

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
                logger.debug(f"Fetched rows: {rows}")

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
            logger.error(f"Error fetching services: {e}")

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


def build_rental_services_txt_bytes() -> tuple[bytes, str]:
    """
    Builds the specific .txt list for Rentals only.
    """
    with get_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT local_code, service_name FROM rental_services ORDER BY local_code ASC;")
            rows = cur.fetchall()

    lines = ["Long-Term Rental Services Catalog", ""]
    
    for r in rows:
        # 👇 Intercept "servicenotlisted" and rename it beautifully for the user
        raw_name = r['service_name'].strip()
        display_name = "All Services" if raw_name.lower() in {"servicenotlisted", "general"} else raw_name

        lines.append(f"Product ID: {str(r['local_code']).zfill(4)}")
        lines.append(f"Service: {display_name}")
        lines.append("______________________\n")

    content = "\n".join(lines) + "\n"
    return content.encode("utf-8"), "rental_services.txt"


def get_rental_service_name_by_code(code: str) -> str | None:
    """
    Looks up the service name EXCLUSIVELY in the rental table.
    """
    code = (code or "").strip()
    if not code.isdigit() or len(code) not in (3, 4):
        return None

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT service_name FROM rental_services WHERE local_code = %s LIMIT 1;",
                (int(code),),
            )
            row = cur.fetchone()
            if row:
                return row[0]
    return None
                 

def get_user_balance_usd(user_id: int) -> float:
    migrate_users_schema()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(balance_usd, 0) FROM users WHERE user_id=%s", (user_id,))
            row = cur.fetchone()
            return float(row[0] if row else 0)


def add_user_balance_usd(user_id: int, amount_usd: float) -> None:
    migrate_users_schema()  # ensure balance columns exist

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (user_id, balance_usd, balance_updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    balance_usd = COALESCE(users.balance_usd, 0) + EXCLUDED.balance_usd,
                    balance_updated_at = NOW()
                """,
                (user_id, amount_usd),
            )
        conn.commit()


def try_debit_user_balance_usd(user_id: int, amount_usd: float) -> bool:
    """
    Atomically subtracts from balance if enough funds exist.
    Returns True if debited, False if insufficient.
    """
    amt = float(amount_usd or 0)
    if amt <= 0:
        return False

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET balance_usd = COALESCE(balance_usd, 0) - %s,
                    balance_updated_at = NOW()
                WHERE user_id = %s
                  AND COALESCE(balance_usd, 0) >= %s
                """,
                (amt, user_id, amt),
            )
            ok = cur.rowcount == 1
        conn.commit()
    return ok


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











def get_user_active_rentals(user_id: int):
    """Fetches all active rentals for a specific user from the database."""
    query = "SELECT rental_id, phone_number, service_name FROM active_rentals WHERE user_id = %s AND status = 'active'"
    try:
        # Assuming get_connection() is already defined in this file
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (user_id,))
                return cur.fetchall()
    except Exception as e:
        print(f"💥 Database Error (get_user_active_rentals): {e}")
        return []  # Return an empty list if it fails so the bot doesn't crash
    
    
def get_rental_details(rental_id: str):
    """Fetches the details of a specific active rental."""
    query = "SELECT phone_number, service_name, always_on, expiration_time FROM active_rentals WHERE rental_id = %s AND status = 'active'"
    try:
        # Make sure get_connection() is accessible here!
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (rental_id,))
                return cur.fetchone()
    except Exception as e:
        print(f"💥 Database Error (get_rental_details): {e}")
        return None
    
    
def mark_rental_expired(rental_id: str):
    """F flips the database status to expired."""
    query = "UPDATE active_rentals SET status = 'expired' WHERE rental_id = %s"
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (rental_id,))
            conn.commit()
    except Exception as e:
        print(f"Failed to mark rental {rental_id} expired: {e}")    
        
        
def auto_expire_rentals():
    """Sweeps the entire database and marks any past-due rentals as expired."""
    query = """
        UPDATE active_rentals 
        SET status = 'expired' 
        WHERE status = 'active' AND expiration_time <= NOW()
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
            conn.commit()
    except Exception as e:
        print(f"Auto-expire sweep failed: {e}")  
        
        
              
def get_all_active_rentals():
    """Fetches all active rentals to reschedule their precise alarms on boot."""
    query = "SELECT rental_id, expiration_time, user_id FROM active_rentals WHERE status = 'active'"
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                return cur.fetchall() # Returns list of (rental_id, exp_time, user_id) tuples
    except Exception as e:
        print(f"Failed to fetch active rentals: {e}")
        return []
    
    

async def rescue_my_number(update, context):
    """Temporary command to inject a 1-year test number directly into the DB."""
    
    # 1. Your exact hardcoded test data
    user_id = 8466713748
    rental_id = "Faje2"
    phone_number = "1111111111"
    service_name = "test"
    
    # 2. Time Jump: Setting expiration to exactly 365 days from now
    expiration_date = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=2)
    
    # 3. The raw SQL injection
    query = """
        INSERT INTO active_rentals 
        (user_id, rental_id, phone_number, service_name, always_on, is_renewable, status, expiration_time)
        VALUES (%s, %s, %s, %s, %s, %s, 'active', %s)
    """
    
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query, 
                    (user_id, rental_id, phone_number, service_name, False, False, expiration_date)
                )
            conn.commit()
            
        await update.message.reply_text(
            f"✅ <b>SUCCESS!</b>\n\nNumber <code>{phone_number}</code> is officially injected into your database with a 365-day expiration.",
            parse_mode="HTML"
        )
        
        
        # --- ADD THIS TO THE BOTTOM OF THE TRY BLOCK IN /rescue ---
        # --- DYNAMIC ALARM CALCULATION ---
        # Calculate exactly how many seconds until your custom expiration date
        now = datetime.datetime.now(datetime.timezone.utc)
        delay_seconds = (expiration_date - now).total_seconds()
        
        if context.job_queue and delay_seconds > 0:
            from handlers.rental import scheduled_expire_rental 
            context.job_queue.run_once(
                scheduled_expire_rental,
                when=delay_seconds,  # ⏰ Perfectly matches your timedelta!
                data={"rental_id": rental_id, "user_id": user_id},
                name=f"expire_{rental_id}"
            )
        
    except Exception as e:
        await update.message.reply_text(f"💥 Error saving to database: {e}")
        
        
def extend_rental_timer(rental_id: str, days_to_add: int):
    """Adds days to a rental's expiration time in the database."""
    query = """
        UPDATE active_rentals 
        SET expiration_time = expiration_time + CAST(%s AS INTERVAL)
        WHERE rental_id = %s
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Tell PostgreSQL exactly how many days to add (e.g., '14 days')
                cur.execute(query, (f"{days_to_add} days", rental_id))
            conn.commit()
    except Exception as e:
        print(f"Failed to extend timer for {rental_id}: {e}")
        raise e # We raise it so the try/except block in rental.py catches it!        