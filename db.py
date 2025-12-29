# db.py (PostgreSQL version)
from utils import normalize_phone_for_db
from datetime import datetime, timedelta
from contextlib import contextmanager
import os
import json

# Use DATABASE_URL from environment or default to local SQLite
DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    # Default to local SQLite for development
    DB_URL = "sqlite:///local_mina.db"
    print("No DATABASE_URL found, using local SQLite database: local_mina.db")

# Determine database type and import appropriate driver
IS_POSTGRES = DB_URL.startswith('postgresql:') or DB_URL.startswith('postgres:')

if IS_POSTGRES:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        PSYCOPG_VERSION = 2
    except ImportError:
        import psycopg
        from psycopg.rows import dict_row
        PSYCOPG_VERSION = 3

@contextmanager
def get_conn():
    """
    Yields a PostgreSQL connection.
    """
    if PSYCOPG_VERSION == 2:
        conn = psycopg2.connect(DB_URL)
    else:
        conn = psycopg.connect(DB_URL)
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass

@contextmanager
def get_cursor():
    """
    Yields a cursor configured to return mapping-like rows.
    Commits on success, rollbacks on exception.
    """
    with get_conn() as conn:
        if PSYCOPG_VERSION == 2:
            cur = conn.cursor(cursor_factory=RealDictCursor)
        else:
            conn.row_factory = dict_row
            cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            try:
                cur.close()
            except Exception:
                pass

def fetchone_normalized(cur):
    """Return dict or None, works with RealDictRow or tuple (fallback)."""
    row = cur.fetchone()
    if not row:
        return None
    if hasattr(row, "items") or isinstance(row, dict):
        return dict(row)
    # tuple fallback: convert to dict using cursor.description
    cols = [d.name for d in cur.description]  # psycopg2 cursor.description objects have .name
    return dict(zip(cols, row))

def create_transcription_job(job_id, phone, gcs_path):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO transcription_jobs (id, phone, gcs_path, status)
            VALUES (%s, %s, %s, 'PENDING')
        """, (job_id, phone, gcs_path))
        conn.commit()

def get_transcription_job(job_id):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id, phone, gcs_path, status
            FROM transcription_jobs
            WHERE id = %s
        """, (job_id,))
        row = cur.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "phone": row[1],
        "gcs_path": row[2],
        "status": row[3]
    }



def mark_job_processing(job_id):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE transcription_jobs
            SET status='PROCESSING', updated_at=NOW()
            WHERE id=%s
        """, (job_id,))
        conn.commit()

def mark_job_done(job_id):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE transcription_jobs
            SET status='DONE', updated_at=NOW()
            WHERE id=%s
        """, (job_id,))
        conn.commit()


def mark_job_failed(job_id, error):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE transcription_jobs
            SET status='FAILED', error=%s, updated_at=NOW()
            WHERE id=%s
        """, (error, job_id))
        conn.commit()



def init_db():
    """Create tables and helpful indexes if they don't exist."""
    with get_conn() as conn, conn.cursor() as cur:
         # Users table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            phone TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            credits_remaining FLOAT DEFAULT 30.0,
            subscription_active BOOLEAN DEFAULT FALSE,
            subscription_expiry TIMESTAMP,
            razorpay_customer_id TEXT
        );
        """)

    

        # Payments table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            phone TEXT,
            razorpay_payment_id TEXT UNIQUE,
            amount INTEGER,
            currency TEXT DEFAULT 'INR',
            status TEXT,
            reference_id TEXT,
            notes JSONB,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP
        );
        """)

        # Meeting notes table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS meeting_notes (
            id SERIAL PRIMARY KEY,
            phone TEXT NOT NULL,
            audio_file TEXT,
            transcript TEXT,
            summary TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # Ensure message_sid column exists for deduping incoming media (used by app.py)
        cur.execute("ALTER TABLE meeting_notes ADD COLUMN IF NOT EXISTS message_sid TEXT;")
        
        # Add language preference column
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS preferred_language TEXT DEFAULT 'hi';")
        
        # Add subscription tier and feature usage tracking
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_tier VARCHAR(20) DEFAULT 'free';")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_voice_minutes_used FLOAT DEFAULT 0.0;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_image_ocr_count INTEGER DEFAULT 0;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_location_checkins INTEGER DEFAULT 0;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS monthly_contacts_saved INTEGER DEFAULT 0;")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS usage_reset_date TIMESTAMP DEFAULT NOW();")
        
        # Add multilang columns for production worker
        cur.execute("ALTER TABLE meeting_notes ADD COLUMN IF NOT EXISTS detected_language VARCHAR(5);")
        cur.execute("ALTER TABLE meeting_notes ADD COLUMN IF NOT EXISTS chosen_language VARCHAR(5);")
        cur.execute("ALTER TABLE meeting_notes ADD COLUMN IF NOT EXISTS job_state VARCHAR(50);")
        cur.execute("ALTER TABLE meeting_notes ADD COLUMN IF NOT EXISTS summary_generated_at TIMESTAMP;")
        
        # Ensure reference_id and notes columns exist in payments table
        cur.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS reference_id TEXT;")
        cur.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS notes JSONB;")

        # Optional: create index for quick lookup + dedupe enforcement (not strictly UNIQUE because some rows may be null)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meeting_notes_message_sid ON meeting_notes (message_sid);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_payments_reference_id ON payments (reference_id);")

        # Add conversational state columns (CRITICAL FOR MEMORY)
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS current_state VARCHAR(100);")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS state_metadata JSONB DEFAULT '{}';")

        # If you want to enforce uniqueness for non-null message_sid values (strong dedupe),
        # create a unique partial index:
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_meeting_notes_message_sid_unique
            ON meeting_notes (message_sid)
            WHERE message_sid IS NOT NULL;
        """)


        # indexes (idempotent with IF NOT EXISTS)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_payments_phone ON payments (phone)")
        # create a unique index on razorpay_payment_id to prevent duplicates
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_razorpay_payment_id ON payments (razorpay_payment_id)")
        
        # Multilang indexes
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meeting_notes_job_state ON meeting_notes(job_state, created_at);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meeting_notes_language_choice ON meeting_notes(phone, id, chosen_language) WHERE chosen_language IS NOT NULL;")
        
        # Update existing records to have proper job_state
        cur.execute("""
            UPDATE meeting_notes 
            SET job_state = CASE 
                WHEN summary IS NOT NULL AND transcript IS NOT NULL THEN 'completed'
                WHEN transcript IS NOT NULL THEN 'transcribed'
                ELSE 'pending'
            END
            WHERE job_state IS NULL
        """)
        
        # Tasks table for voice-based task creation
        cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT,
            due_at TIMESTAMP,
            priority INTEGER DEFAULT 3,
            status VARCHAR(20) DEFAULT 'open',
            source VARCHAR(50) DEFAULT 'whatsapp',
            metadata JSONB,
            recurring_rule TEXT,
            deleted BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """)
        
        # Reminders table for scheduled task reminders
        cur.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            remind_at TIMESTAMP NOT NULL,
            sent BOOLEAN DEFAULT FALSE,
            sent_at TIMESTAMP,
            attempts INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)
        
        # Task shares for team collaboration
        cur.execute("""
        CREATE TABLE IF NOT EXISTS task_shares (
            id SERIAL PRIMARY KEY,
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            team_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            permission VARCHAR(20) DEFAULT 'view',
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)
        
        # Task tags
        cur.execute("""
        CREATE TABLE IF NOT EXISTS task_tags (
            id SERIAL PRIMARY KEY,
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            tag VARCHAR(100) NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)
        
        # Create indexes for performance
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user_status ON tasks(user_id, status, deleted);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_due_at ON tasks(due_at) WHERE status='open' AND deleted=false;")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_reminders_sent ON reminders(sent, remind_at);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_task_shares_task_id ON task_shares(task_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_task_tags_task_id ON task_tags(task_id);")
        
        # Meeting bots table for live meeting transcription
        cur.execute("""
        CREATE TABLE IF NOT EXISTS meeting_bots (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            meeting_url TEXT NOT NULL,
            bot_id TEXT,
            platform VARCHAR(20),
            status VARCHAR(20) DEFAULT 'pending',
            transcript TEXT,
            live_transcript TEXT,
            summary TEXT,
            participants JSONB,
            recording_url TEXT,
            started_at TIMESTAMP,
            ended_at TIMESTAMP,
            last_update_sent_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)
        
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meeting_bots_user_status ON meeting_bots(user_id, status);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meeting_bots_bot_id ON meeting_bots(bot_id);")
        
        # NEW FEATURES TABLES (Create after users and tasks tables exist)
        
        # Location check-ins table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS location_checkins (
            id SERIAL PRIMARY KEY,
            user_phone TEXT NOT NULL,
            latitude DECIMAL(10, 8),
            longitude DECIMAL(11, 8),
            address TEXT,
            checkin_time TIMESTAMP DEFAULT NOW(),
            checkout_time TIMESTAMP,
            notes TEXT,
            photos JSONB,
            task_id INTEGER,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)
        
        # Contacts table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id SERIAL PRIMARY KEY,
            user_phone TEXT NOT NULL,
            contact_name TEXT NOT NULL,
            contact_number TEXT NOT NULL,
            contact_email TEXT,
            company TEXT,
            notes TEXT,
            source VARCHAR(50) DEFAULT 'manual',
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(user_phone, contact_number)
        );
        """)
        
        # Image OCR activities table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS image_activities (
            id SERIAL PRIMARY KEY,
            user_phone TEXT NOT NULL,
            image_url TEXT,
            extracted_text TEXT,
            activity_type VARCHAR(50),
            result_data JSONB,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)
        
        # User activities log table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_activities (
            id SERIAL PRIMARY KEY,
            user_phone TEXT NOT NULL,
            activity_type VARCHAR(50) NOT NULL,
            activity_data JSONB,
            source VARCHAR(50) DEFAULT 'whatsapp',
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)
        
        # Custom reminders table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS custom_reminders (
            id SERIAL PRIMARY KEY,
            user_phone TEXT NOT NULL,
            reminder_text TEXT NOT NULL,
            remind_at TIMESTAMP NOT NULL,
            sent BOOLEAN DEFAULT FALSE,
            sent_at TIMESTAMP,
            source_meeting_id INTEGER,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)
        
        # Ensure task_id column exists in location_checkins table
        cur.execute("ALTER TABLE location_checkins ADD COLUMN IF NOT EXISTS task_id INTEGER;")
        
        # Create indexes for new tables
        cur.execute("CREATE INDEX IF NOT EXISTS idx_location_checkins_user_time ON location_checkins(user_phone, checkin_time);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_contacts_user_phone ON contacts(user_phone);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_image_activities_user_type ON image_activities(user_phone, activity_type);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_activities_user_type ON user_activities(user_phone, activity_type, created_at);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_custom_reminders_remind_at ON custom_reminders(remind_at, sent);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_location_checkins_task_id ON location_checkins(task_id);")
        
        conn.commit()


def get_user(phone):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE phone=%s", (phone,))
        return cur.fetchone()

def save_user(user):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO users (phone, created_at, credits_remaining, subscription_active, subscription_expiry, razorpay_customer_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (phone)
            DO UPDATE SET
              created_at = EXCLUDED.created_at,
              credits_remaining = EXCLUDED.credits_remaining,
              subscription_active = EXCLUDED.subscription_active,
              subscription_expiry = EXCLUDED.subscription_expiry,
              razorpay_customer_id = EXCLUDED.razorpay_customer_id
        """, (
            user.get("phone"),
            user.get("created_at"),
            user.get("credits_remaining"),
            user.get("subscription_active"),
            user.get("subscription_expiry"),
            user.get("razorpay_customer_id")
        ))
        conn.commit()

def get_or_create_user(raw_phone: str):
    phone = normalize_phone_for_db(raw_phone)
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:

        cur.execute("SELECT * FROM users WHERE phone = %s", (phone,))
        row = cur.fetchone()
        if row:
            return dict(row)
        # create default user row
        cur.execute("""
            INSERT INTO users (phone, credits_remaining, subscription_active, subscription_expiry, preferred_language, created_at)
            VALUES (%s, %s, %s, %s, %s, now())
            RETURNING *
        """, (phone, 30.0, False, None, 'hi'))
        new_row = cur.fetchone()
        conn.commit()
        return dict(new_row) if new_row else None

def deduct_minutes(phone, minutes):
    user = get_user(phone)
    if not user:
        user = get_or_create_user(phone)
    if user["subscription_active"]:
        return float("inf")
    remaining = float(user["credits_remaining"] or 0.0)
    remaining_after = max(0.0, remaining - float(minutes))
    user["credits_remaining"] = remaining_after
    save_user(user)
    return remaining_after

def get_remaining_minutes(phone):
    user = get_user(phone)
    if not user:
        return 0.0
    if user["subscription_active"]:
        return float("inf")
    return float(user["credits_remaining"] or 0.0)

def set_subscription_active(phone, days=30):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE users
            SET subscription_active = TRUE,
                subscription_expiry = NOW() + (%s || ' days')::interval,
                credits_remaining = GREATEST(COALESCE(credits_remaining, 0), 0)
            WHERE phone = %s
        """, (days, phone))
        conn.commit()


# db.py (partial) — replace record_payment with this
from datetime import datetime

def record_payment(phone, razorpay_payment_id, amount, currency="INR", status="created", reference_id=None, notes=None):
    """
    Insert or update a payment row for razorpay_payment_id.
    Idempotent — repeated calls update existing row.
    Returns (id, status).
    """
    from datetime import datetime
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO payments (phone, razorpay_payment_id, amount, currency, status, reference_id, notes, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (razorpay_payment_id)
            DO UPDATE SET
                phone = COALESCE(EXCLUDED.phone, payments.phone),
                amount = EXCLUDED.amount,
                currency = EXCLUDED.currency,
                status = EXCLUDED.status,
                reference_id = COALESCE(EXCLUDED.reference_id, payments.reference_id),
                notes = COALESCE(EXCLUDED.notes, payments.notes),
                updated_at = EXCLUDED.updated_at
            RETURNING id, status;
        """, (
            phone,
            razorpay_payment_id,
            amount,
            currency,
            status,
            reference_id,
            json.dumps(notes) if notes is not None else None,
            datetime.utcnow(),
            datetime.utcnow()
        ))
        row = cur.fetchone()
        conn.commit()
        if not row:
            return None, None
        # handle RealDictCursor vs tuple
        if isinstance(row, dict):
            return row.get("id"), row.get("status")
        return row[0], row[1]


def save_meeting_notes(phone, audio_file, transcript, summary):
    """
    Store the meeting transcription + summary for a user.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO meeting_notes (phone, audio_file, transcript, summary, created_at)
            VALUES (%s, %s, %s, %s, NOW())
        """, (phone, audio_file, transcript, summary))
        conn.commit()

def save_meeting_notes_with_sid(raw_phone, audio_file, transcript, summary, message_sid=None):
    """
    Save meeting notes and dedupe by message_sid.
    Accepts phone as raw string (e.g. '+919876543210' or 'whatsapp:+919876543210').
    Returns dict {id: ..., skipped: True/False}
    """
    phone = normalize_phone_for_db(raw_phone)
    with get_conn() as conn, conn.cursor() as cur:
        if message_sid:
            cur.execute("SELECT 1 FROM meeting_notes WHERE message_sid=%s LIMIT 1", (message_sid,))
            if cur.fetchone():
                return {"skipped": True, "id": None}

        cur.execute("""
            INSERT INTO meeting_notes (phone, audio_file, transcript, summary, message_sid, created_at)
            VALUES (%s, %s, %s, %s, %s, now())
            RETURNING id
        """, (phone, audio_file, transcript, summary, message_sid))
        row = cur.fetchone()
        conn.commit()
        return {"skipped": False, "id": row[0] if row else None}



def upsert_payment_and_activate(raw_phone, razorpay_payment_id, amount, status):
    """
    Upsert a payment row using razorpay_payment_id unique index and activate user if status=='captured'
    """
    phone = normalize_phone_for_db(raw_phone)
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:

        # Upsert payment (requires unique index on razorpay_payment_id)
        cur.execute("""
          INSERT INTO payments (phone, razorpay_payment_id, amount, status, created_at)
          VALUES (%s, %s, %s, %s, now())
          ON CONFLICT (razorpay_payment_id)
          DO UPDATE SET status = EXCLUDED.status, amount = EXCLUDED.amount
          RETURNING id, razorpay_payment_id, status;
        """, (phone, razorpay_payment_id, amount, status))
        payment_row = cur.fetchone()

        activated = False
        if status and str(status).lower() == 'captured':
            # create user if missing, and activate/extend subscription
            cur.execute("""
                INSERT INTO users (phone, credits_remaining, subscription_active, subscription_expiry, created_at)
                VALUES (%s, %s, TRUE, now() + interval '30 days', now())
                ON CONFLICT (phone) DO UPDATE
                  SET subscription_active = TRUE,
                      subscription_expiry = now() + interval '30 days'
                RETURNING phone, subscription_active, subscription_expiry;
            """, (phone, 30.0))
            _ = cur.fetchone()
            activated = True

        conn.commit()
        return {"payment": dict(payment_row) if payment_row else None, "activated": activated}

def get_user_by_phone(raw_phone):
    phone = normalize_phone_for_db(raw_phone)
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM users WHERE phone = %s", (phone,))
        row = cur.fetchone()
        return dict(row) if row else None

def get_user_credits(raw_phone):
    """Get current credit balance for user"""
    phone = normalize_phone_for_db(raw_phone)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT credits_remaining FROM users WHERE phone = %s", (phone,))
        row = cur.fetchone()
        return float(row[0]) if row and row[0] is not None else 0.0
    
def decrement_minutes_if_available(raw_phone, minutes_to_deduct: float):
    phone = normalize_phone_for_db(raw_phone)
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:

        # fetch current values
        cur.execute("SELECT credits_remaining, subscription_active, subscription_expiry FROM users WHERE phone = %s FOR UPDATE", (phone,))
        row = cur.fetchone()
        if not row:
            # user missing — create default
            cur.execute("INSERT INTO users (phone, credits_remaining) VALUES (%s, %s) RETURNING credits_remaining", (phone, 30.0))
            row = cur.fetchone()

        # If subscription active & not expired, allow unlimited (or don't decrement)
        sub_active = bool(row.get('subscription_active'))
        expiry = row.get('subscription_expiry')
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        if sub_active and (expiry is None or expiry > now):
            # subscription active: do not deduct (or deduct differently)
            conn.commit()
            return {"ok": True, "deducted": 0.0, "remaining": row.get('credits_remaining')}

        current = float(row.get('credits_remaining') or 0.0)
        if current < minutes_to_deduct:
            return {"ok": False, "reason": "insufficient_credits", "remaining": current}
        new_remaining = current - minutes_to_deduct
        cur.execute("UPDATE users SET credits_remaining = %s WHERE phone = %s", (new_remaining, phone))
        conn.commit()
        return {"ok": True, "deducted": minutes_to_deduct, "remaining": new_remaining}




# --- Task CRUD ---
def create_task(phone_or_user_id, title, description=None, due_at=None, priority=3, source='whatsapp', metadata=None, recurring_rule=None):
    """
    Accepts either normalized phone string OR user_id integer.
    Returns created task row as dict.
    """
    metadata = metadata or {}
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        if isinstance(phone_or_user_id, str):
            user = get_or_create_user(phone_or_user_id)
            user_id = user['id']
        else:
            user_id = int(phone_or_user_id)

        cur.execute("""
            INSERT INTO tasks (user_id, title, description, due_at, priority, source, metadata, recurring_rule, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), now())
            RETURNING *;
        """, (user_id, title, description, due_at, priority, source, json.dumps(metadata), recurring_rule))
        row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None

def get_tasks_for_user(phone_or_user_id, status='open', limit=50):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        if isinstance(phone_or_user_id, str):
            user = get_user_by_phone(phone_or_user_id)
            if not user:
                return []
            user_id = user['id']
        else:
            user_id = int(phone_or_user_id)
        cur.execute("""
            SELECT * FROM tasks
            WHERE user_id = %s AND status = %s AND deleted = false
            ORDER BY due_at NULLS LAST, created_at DESC
            LIMIT %s;
        """, (user_id, status, limit))
        rows = cur.fetchall()
        return [dict(r) for r in rows]

def mark_task_done(task_id, phone_or_user_id=None):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        # optional ownership check
        if phone_or_user_id is not None:
            if isinstance(phone_or_user_id, str):
                user = get_user_by_phone(phone_or_user_id)
                if not user:
                    return False
                user_id = user['id']
            else:
                user_id = int(phone_or_user_id)
            cur.execute("UPDATE tasks SET status='done', updated_at=now() WHERE id=%s AND user_id=%s RETURNING *", (task_id, user_id))
        else:
            cur.execute("UPDATE tasks SET status='done', updated_at=now() WHERE id=%s RETURNING *", (task_id,))
        updated = cur.fetchone()
        # cancel pending reminders
        cur.execute("UPDATE reminders SET sent = true, sent_at = now() WHERE task_id = %s AND sent = false", (task_id,))
        conn.commit()
        return dict(updated) if updated else None

# --- Reminders ---
def get_pending_reminders(limit=100):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT r.*, t.title AS task_title, u.phone AS phone
            FROM reminders r
            JOIN tasks t ON t.id = r.task_id
            JOIN users u ON u.id = r.user_id
            WHERE r.sent = false AND r.remind_at <= now()
            ORDER BY r.remind_at
            LIMIT %s
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]

def mark_reminder_sent(reminder_id):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE reminders SET sent = true, sent_at = now(), attempts = attempts + 1 WHERE id = %s", (reminder_id,))
        conn.commit()

# --- Search helper ---
import json
def search_tasks(phone_or_user_id, query_text, limit=25):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        if isinstance(phone_or_user_id, str):
            user = get_user_by_phone(phone_or_user_id)
            if not user:
                return []
            user_id = user['id']
        else:
            user_id = int(phone_or_user_id)

        cur.execute("""
            SELECT id, title, description, due_at, status
            FROM tasks
            WHERE user_id = %s AND search_vector @@ plainto_tsquery('simple', %s)
            ORDER BY due_at NULLS LAST
            LIMIT %s
        """, (user_id, query_text, limit))
        return [dict(r) for r in cur.fetchall()]

# --- Sharing & tags ---
def share_task(task_id, team_user_phone_or_id, permission='view'):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        if isinstance(team_user_phone_or_id, str):
            partner = get_or_create_user(team_user_phone_or_id)
            team_user_id = partner['id']
        else:
            team_user_id = int(team_user_phone_or_id)
        cur.execute("""
           INSERT INTO task_shares (task_id, team_user_id, permission, created_at)
           VALUES (%s, %s, %s, now())
           ON CONFLICT DO NOTHING
           RETURNING *;
        """, (task_id, team_user_id, permission))
        row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None

def add_tag(task_id, tag):
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("INSERT INTO task_tags (task_id, tag, created_at) VALUES (%s, %s, now()) ON CONFLICT DO NOTHING RETURNING *", (task_id, tag))
        row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None

def set_user_language(phone, language_code):
    """Set user's preferred language"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET preferred_language = %s WHERE phone = %s", (language_code, phone))
        conn.commit()

def get_user_language(phone):
    """Get user's preferred language, default to Hindi"""
    user = get_user(phone)
    return user.get('preferred_language', 'hi') if user else 'hi'

def update_user_language(phone: str, language_code: str):
    """
    Set or update the user's preferred language in the users table.
    Returns the updated row as a dict (id, phone, language) or None on failure.
    """
    try:
        with get_conn() as conn, conn.cursor() as cur:
            # Try to update existing user
            cur.execute(
                "UPDATE users SET language = %s WHERE phone = %s RETURNING id, phone, language",
                (language_code, phone)
            )
            row = cur.fetchone()
            if row:
                conn.commit()
                return {"id": row[0], "phone": row[1], "language": row[2]}

            # If no existing row, insert new (safe fallback)
            cur.execute(
                "INSERT INTO users (phone, language) VALUES (%s, %s) RETURNING id, phone, language",
                (phone, language_code)
            )
            row = cur.fetchone()
            conn.commit()
            if row:
                return {"id": row[0], "phone": row[1], "language": row[2]}

    except Exception as e:
        print("DB: update_user_language error:", e)
    return None


# SUBSCRIPTION TIER MANAGEMENT

def get_user_subscription_tier(phone):
    """Get user's subscription tier"""
    user = get_user_by_phone(phone)
    return user.get('subscription_tier', 'free') if user else 'free'

def check_feature_limit(phone, feature_type):
    """Check if user can use a feature based on their subscription tier"""
    user = get_user_by_phone(phone)
    if not user:
        return False, "User not found"
    
    tier = user.get('subscription_tier', 'free')
    
    # Reset monthly counters if needed
    reset_monthly_usage_if_needed(phone)
    
    # Feature limits by tier
    limits = {
        'free': {
            'voice_minutes': 15,  # Reduced to create bigger gap
            'image_ocr': 3,       # Reduced to create urgency
            'location_checkins': 5,  # Minimal for testing
            'contacts_saved': 10     # Just enough to try
        },
        'basic': {  # ₹299
            'voice_minutes': 90,     # 6x increase from FREE
            'image_ocr': 40,         # 13x increase from FREE
            'location_checkins': 75, # 15x increase from FREE
            'contacts_saved': 150    # 15x increase from FREE
        },
        'premium': {  # ₹499
            'voice_minutes': float('inf'),
            'image_ocr': float('inf'),
            'location_checkins': float('inf'),
            'contacts_saved': float('inf')
        }
    }
    
    if tier not in limits:
        return False, "Invalid subscription tier"
    
    tier_limits = limits[tier]
    
    if feature_type == 'voice_minutes':
        used = user.get('monthly_voice_minutes_used', 0)
        limit = tier_limits['voice_minutes']
    elif feature_type == 'image_ocr':
        used = user.get('monthly_image_ocr_count', 0)
        limit = tier_limits['image_ocr']
    elif feature_type == 'location_checkins':
        used = user.get('monthly_location_checkins', 0)
        limit = tier_limits['location_checkins']
    elif feature_type == 'contacts_saved':
        used = user.get('monthly_contacts_saved', 0)
        limit = tier_limits['contacts_saved']
    else:
        return False, "Unknown feature type"
    
    if used >= limit:
        return False, f"Monthly limit reached ({used}/{limit}). Upgrade to continue."
    
    return True, f"Usage: {used}/{limit}"

def increment_feature_usage(phone, feature_type, amount=1):
    """Increment feature usage counter"""
    with get_conn() as conn, conn.cursor() as cur:
        if feature_type == 'voice_minutes':
            cur.execute("UPDATE users SET monthly_voice_minutes_used = monthly_voice_minutes_used + %s WHERE phone = %s", (amount, phone))
        elif feature_type == 'image_ocr':
            cur.execute("UPDATE users SET monthly_image_ocr_count = monthly_image_ocr_count + %s WHERE phone = %s", (amount, phone))
        elif feature_type == 'location_checkins':
            cur.execute("UPDATE users SET monthly_location_checkins = monthly_location_checkins + %s WHERE phone = %s", (amount, phone))
        elif feature_type == 'contacts_saved':
            cur.execute("UPDATE users SET monthly_contacts_saved = monthly_contacts_saved + %s WHERE phone = %s", (amount, phone))
        conn.commit()

def reset_monthly_usage_if_needed(phone):
    """Reset monthly usage counters if a month has passed"""
    user = get_user_by_phone(phone)
    if not user:
        return
    
    reset_date = user.get('usage_reset_date')
    if not reset_date:
        return
    
    # Check if a month has passed
    from datetime import datetime
    now = datetime.now()
    if isinstance(reset_date, str):
        reset_date = datetime.fromisoformat(reset_date.replace('Z', '+00:00'))
    
    if (now - reset_date).days >= 30:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE users SET 
                    monthly_voice_minutes_used = 0,
                    monthly_image_ocr_count = 0,
                    monthly_location_checkins = 0,
                    monthly_contacts_saved = 0,
                    usage_reset_date = NOW()
                WHERE phone = %s
            """, (phone,))
            conn.commit()

def upgrade_user_subscription(phone, tier, duration_days=30):
    """Upgrade user to a subscription tier"""
    with get_conn() as conn, conn.cursor() as cur:
        expiry = datetime.now() + timedelta(days=duration_days)
        cur.execute("""
            UPDATE users SET 
                subscription_tier = %s,
                subscription_active = TRUE,
                subscription_expiry = %s
            WHERE phone = %s
        """, (tier, expiry, phone))
        conn.commit()

def get_upgrade_message(current_tier):
    """Get upgrade message based on current tier"""
    if current_tier == 'free':
        return (
            "🚀 *Upgrade to unlock more features!*\n\n"
            "💎 **BASIC (₹299/month)**\n"
            "• 60 minutes voice transcription\n"
            "• 25 image OCR scans\n"
            "• 50 location check-ins\n"
            "• 100 contacts storage\n\n"
            "🏆 **PREMIUM (₹499/month)**\n"
            "• Unlimited everything\n"
            "• Priority support\n"
            "• Advanced analytics\n"
            "• Team collaboration\n\n"
            "💳 Pay securely: https://rzp.io/rzp/X6bzLXmD"
        )
    elif current_tier == 'basic':
        return (
            "🏆 *Upgrade to PREMIUM for unlimited access!*\n\n"
            "**PREMIUM (₹499/month)**\n"
            "• Unlimited voice transcription\n"
            "• Unlimited image OCR\n"
            "• Unlimited location tracking\n"
            "• Unlimited contacts\n"
            "• Priority support\n"
            "• Advanced analytics\n\n"
            "💳 Upgrade now: https://rzp.io/rzp/X6bzLXmD"
        )
    else:
        return "✨ You're already on our highest tier! Enjoy unlimited access."

# NEW FEATURES DATABASE FUNCTIONS

def log_location_checkin(phone, latitude, longitude, address=None, task_id=None):
    """Log location check-in to database"""
    # Check feature limit before processing
    can_use, message = check_feature_limit(phone, 'location_checkins')
    if not can_use:
        return None  # Will be handled by calling function
    
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            INSERT INTO location_checkins (user_phone, latitude, longitude, address, task_id, checkin_time)
            VALUES (%s, %s, %s, %s, %s, now())
            RETURNING *
        """, (phone, latitude, longitude, address, task_id))
        row = cur.fetchone()
        conn.commit()
        
        # Increment usage counter
        increment_feature_usage(phone, 'location_checkins', 1)
        
        return dict(row) if row else None

def log_contact_save(phone, contact_name, contact_number, contact_email=None, company=None, source='whatsapp'):
    """Save contact to database"""
    # Check feature limit before processing
    can_use, message = check_feature_limit(phone, 'contacts_saved')
    if not can_use:
        return None  # Will be handled by calling function
    
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            INSERT INTO contacts (user_phone, contact_name, contact_number, contact_email, company, source)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_phone, contact_number) 
            DO UPDATE SET 
                contact_name = EXCLUDED.contact_name,
                contact_email = EXCLUDED.contact_email,
                company = EXCLUDED.company
            RETURNING *
        """, (phone, contact_name, contact_number, contact_email, company, source))
        row = cur.fetchone()
        conn.commit()
        
        # Increment usage counter (only for new contacts)
        if row:
            increment_feature_usage(phone, 'contacts_saved', 1)
        
        return dict(row) if row else None

def log_image_activity(phone, image_url, extracted_text, activity_type, result_data=None):
    """Log image OCR activity to database"""
    # Check feature limit before processing
    can_use, message = check_feature_limit(phone, 'image_ocr')
    if not can_use:
        return None  # Will be handled by calling function
    
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            INSERT INTO image_activities (user_phone, image_url, extracted_text, activity_type, result_data)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
        """, (phone, image_url, extracted_text, activity_type, json.dumps(result_data) if result_data else None))
        row = cur.fetchone()
        conn.commit()
        
        # Increment usage counter
        increment_feature_usage(phone, 'image_ocr', 1)
        
        return dict(row) if row else None

def log_user_activity(phone, activity_type, activity_data=None, source='whatsapp'):
    """Log general user activity to database"""
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            INSERT INTO user_activities (user_phone, activity_type, activity_data, source)
            VALUES (%s, %s, %s, %s)
            RETURNING *
        """, (phone, activity_type, json.dumps(activity_data) if activity_data else None, source))
        row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None

def save_custom_reminder(phone, reminder_text, remind_at, source_meeting_id=None):
    """Save custom reminder to database"""
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            INSERT INTO custom_reminders (user_phone, reminder_text, remind_at, source_meeting_id)
            VALUES (%s, %s, %s, %s)
            RETURNING *
        """, (phone, reminder_text, remind_at, source_meeting_id))
        row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None
    

# --- Conversational State Management (The Fix for "Amnesia") ---

def set_user_state(phone, state, metadata=None):
    """
    Saves the user's current conversational state to the DB.
    survives restarts.
    """
    phone = normalize_phone_for_db(phone)
    if metadata is None:
        metadata = {}
        
    with get_conn() as conn, conn.cursor() as cur:
        # Ensure user exists first
        get_or_create_user(phone)
        
        cur.execute("""
            UPDATE users 
            SET current_state = %s, 
                state_metadata = %s 
            WHERE phone = %s
        """, (state, json.dumps(metadata), phone))
        conn.commit()

def get_user_state(phone):
    """
    Retrieves the user's state from the DB.
    Returns (state_string, metadata_dict).
    """
    phone = normalize_phone_for_db(phone)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT current_state, state_metadata FROM users WHERE phone = %s", (phone,))
        row = cur.fetchone()
        
        if row:
            # Handle RealDictCursor or tuple
            if isinstance(row, dict):
                state = row.get('current_state')
                meta = row.get('state_metadata')
            else:
                state = row[0]
                meta = row[1]
                
            # Parse JSON if it comes back as a string (depends on driver)
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except:
                    meta = {}
            if meta is None:
                meta = {}
                
            return state, meta
        
    return None, {}
