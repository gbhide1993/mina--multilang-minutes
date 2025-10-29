# db_multilang.py - Database functions for multi-language support
import os
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

from db import get_conn, get_user

def init_multilang_db():
    """Add language preference column if not exists"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS preferred_language TEXT DEFAULT 'hi';")
        conn.commit()

def set_user_language(phone, language_code):
    """Set user's preferred language"""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET preferred_language = %s WHERE phone = %s", (language_code, phone))
        conn.commit()

def get_user_language(phone):
    """Get user's preferred language, default to Hindi"""
    try:
        user = get_user(phone)
        if user:
            if hasattr(user, 'get'):
                lang = user.get('preferred_language')
                return lang if lang else 'hi'
            elif hasattr(user, '__getitem__') and len(user) > 6:
                lang = user[6] if len(user) > 6 else None
                return lang if lang else 'hi'
            else:
                return 'hi'
        return 'hi'
    except Exception as e:
        print(f"Warning: get_user_language failed for {phone}: {e}")
        return 'hi'

def is_user_language_explicitly_set(phone):
    """Check if user has explicitly set a language preference"""
    try:
        user = get_user(phone)
        if user:
            if hasattr(user, 'get'):
                return user.get('preferred_language') is not None
            elif hasattr(user, '__getitem__') and len(user) > 6:
                return user[6] is not None
        return False
    except Exception as e:
        print(f"Warning: is_user_language_explicitly_set failed for {phone}: {e}")
        return False

def get_user_credits(phone):
    """Get user's remaining credits"""
    try:
        user = get_user(phone)
        if user:
            if hasattr(user, 'get'):
                return float(user.get('credits_remaining', 0.0))
            elif hasattr(user, '__getitem__'):
                return float(user[2] or 0.0)  # credits_remaining is 3rd column
        return 0.0
    except Exception as e:
        print(f"Warning: get_user_credits failed for {phone}: {e}")
        return 0.0
