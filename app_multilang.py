# app_multilang.py - Multi-language version of app.py
"""
Multi-language WhatsApp Meeting Minutes App
Based on app.py but with 9 Indian language support
Includes ALL features: payments, admin endpoints, Redis optimization, etc.
"""

import os
import time
import json
import tempfile
import mimetypes
import traceback
import openai 
from datetime import datetime, timedelta
from urllib.parse import urlparse, unquote
import hashlib
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from twilio.rest import Client as TwilioClient
from mutagen import File as MutagenFile
from utils import send_whatsapp
from openai_client_multilang import transcribe_file_multilang, summarize_text_multilang
from redis_conn import get_redis_conn_or_raise, get_queue, get_redis_url
from redis import from_url

# Import DB and payments (same as original)
from db import (init_db, get_conn, get_or_create_user, get_remaining_minutes, deduct_minutes, save_meeting_notes, save_meeting_notes_with_sid, save_user, decrement_minutes_if_available, set_subscription_active)
from db_multilang import init_multilang_db, set_user_language, get_user_language
from language_handler_v2 import get_language_menu, parse_language_choice, get_language_name
import re
from payments import create_payment_link_for_phone, handle_webhook_event, verify_razorpay_webhook

# Load environment (same as original)
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM") or os.getenv("TWILIO_FROM")
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")
LANGUAGE = os.getenv("LANGUAGE", "en")
DATABASE_URL = os.getenv("DATABASE_URL")
DEFAULT_SUBSCRIPTION_MINUTES = float(os.getenv("DEFAULT_SUBSCRIPTION_MINUTES", "30.0"))

# Twilio client
twilio_client = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    try:
        twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    except Exception as e:
        print("Failed to init Twilio client:", e)

# Ensure DB schema exists (safe to call)
try:
    init_db()
    init_multilang_db()
    print("✅ Database and multi-language support initialized")
except Exception as e:
    print("init_db() failed:", e)

app = Flask(__name__)

# Create temp directory for audio files
TEMP_DIR = os.getenv("TEMP_DIR", os.getcwd())
os.makedirs(TEMP_DIR, exist_ok=True)

# Initialize Redis safely after Flask app is created
try:
    redis_conn = get_redis_conn_or_raise()
    queue = get_queue()
    redis_url = get_redis_url()
    print("✅ Redis connection and queue initialized.")
except Exception as e:
    print("⚠️ Failed to initialize Redis:", e)
    redis_conn = None
    queue = None
    redis_url = None

# Utility functions (same as original)
def debug_print(*args, **kwargs):
    """Simple wrapper for prints so we can change later to logging."""
    print(*args, **kwargs)

def _ext_from_content_type(ct: str):
    if not ct:
        return None
    ct = ct.split(";")[0].strip().lower()
    mapping = {
        "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a",
        "audio/mp4a-latm": ".m4a", "audio/aac": ".aac", "audio/wav": ".wav", "audio/x-wav": ".wav",
        "audio/ogg": ".ogg", "audio/opus": ".opus", "audio/webm": ".webm", "audio/amr": ".amr",
        "audio/3gpp": ".3gp", "video/3gpp": ".3gp", "video/mp4": ".mp4", "audio/x-caf": ".caf", "audio/x-aiff": ".aiff"
    }
    return mapping.get(ct)

def download_media_to_local(url, fallback_ext=".m4a"):
    """Download Twilio media (with Basic Auth if needed) to temp file and return local path."""
    if not url:
        debug_print("download_media_to_local: no url")
        return None
    try:
        auth = None
        parsed = urlparse(url)
        if "twilio.com" in parsed.netloc and TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
            auth = (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        resp = requests.get(url, stream=True, timeout=60, auth=auth)
        resp.raise_for_status()
    except Exception as e:
        debug_print("download_media_to_local: request failed:", e)
        return None

    ct = resp.headers.get("Content-Type", "")
    ext = _ext_from_content_type(ct) or os.path.splitext(unquote(parsed.path))[1] or fallback_ext
    tmp_path = os.path.join(TEMP_DIR, f"temp_audio_{int(time.time())}{ext}")
    try:
        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                if chunk:
                    f.write(chunk)
        debug_print(f"Saved media to {tmp_path} (Content-Type: {ct})")
        return tmp_path
    except Exception as e:
        debug_print("download_media_to_local: write failed:", e)
        return None

def get_audio_duration_seconds(path: str) -> float:
    """Get audio duration with support for all Android/iOS formats."""
    try:
        mf = MutagenFile(path)
        if mf and hasattr(mf, 'info') and hasattr(mf.info, 'length'):
            return float(mf.info.length)
    except Exception as e:
        debug_print("Mutagen parsing failed:", e)
    
    try:
        size_bytes = os.path.getsize(path)
        ext = path.lower().split('.')[-1]
        bitrate_map = {
            'ogg': 64000, 'opus': 64000, 'm4a': 96000, 'aac': 96000, 'mp3': 128000,
            'wav': 1411200, 'amr': 12200, '3gp': 12200, 'webm': 64000, 'mp4': 96000
        }
        bitrate = bitrate_map.get(ext, 96000)
        seconds = (size_bytes * 8) / bitrate
        return max(seconds, 1.0)
    except Exception as e2:
        debug_print("File size fallback failed:", e2)
        return 30.0

def normalize_phone_for_db(phone):
    """Ensure consistent phone format for DB keys."""
    if not phone:
        return None
    return phone.strip().lower().replace(" ", "")

def _get_pending_summary_job(phone):
    """Check if user has a pending summary job awaiting language selection"""
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT id, summary FROM meeting_notes 
                WHERE phone=%s AND transcript IS NOT NULL AND summary LIKE '%awaiting_language_selection%'
                ORDER BY created_at DESC LIMIT 1
            """, (phone,))
            row = cur.fetchone()
            if row:
                try:
                    job_data = json.loads(row[1] if hasattr(row, '__getitem__') else row.summary)
                    if job_data.get('status') == 'awaiting_language_selection':
                        job_data['meeting_id'] = row[0] if hasattr(row, '__getitem__') else row.id
                        return job_data
                except:
                    pass
    except Exception as e:
        debug_print(f"Error checking pending jobs: {e}")
    return None

@app.route("/twilio-webhook-multilang", methods=["POST"])
def twilio_webhook_multilang():
    """Multi-language webhook handler with ALL original features"""
    # Log all incoming requests for debugging
    from datetime import datetime as dt
    print(f"📞 MULTILANG WEBHOOK: Received request from {request.remote_addr} at {dt.utcnow()}")
    print(f"📞 MULTILANG WEBHOOK: Headers: {dict(request.headers)}")
    print(f"📞 MULTILANG WEBHOOK: Form data: {dict(request.form)}")
    
    try:
        sender_raw = request.values.get("From") or request.form.get("From")
        sender = normalize_phone_for_db(sender_raw)
        message_sid = request.values.get("MessageSid") or request.form.get("MessageSid")
        media_url = request.values.get("MediaUrl0") or request.form.get("MediaUrl0")
        # compute media_hash fallback if no MessageSid
        media_hash = None
        if not message_sid and media_url:
            media_hash = hashlib.sha256(media_url.encode("utf-8")).hexdigest()
        dedupe_key = message_sid or media_hash

        # Check dedupe before doing heavy work
        if dedupe_key:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT 1 FROM meeting_notes WHERE message_sid=%s LIMIT 1", (dedupe_key,))
                if cur.fetchone():
                    print("Duplicate message detected (dedupe_key). Skipping processing.")
                    return ("", 204)
        
        # Handle text messages for language selection
        body_text = (request.values.get("Body") or request.form.get("Body") or "").strip()
        if not media_url:
            # Language menu request
            if body_text.lower() in ['language', 'lang', 'settings', 'भाषा', 'ভাষা']:
                menu = get_language_menu()
                send_whatsapp(sender, menu)
                return ("", 204)
            
            # Language choice - could be preference setting OR summary language selection
            lang_choice = parse_language_choice(body_text)
            if lang_choice:
                # Check if user has a pending summary job
                pending_job = _get_pending_summary_job(sender)
                if pending_job:
                    # Complete the summary job with selected language
                    from worker_multilang import complete_summary_job
                    result = complete_summary_job(pending_job['meeting_id'], lang_choice)
                    if result.get('success'):
                        lang_name = get_language_name(lang_choice)
                        send_whatsapp(sender, f"✅ Generating summary in {lang_name}...")
                    else:
                        send_whatsapp(sender, "⚠️ Failed to generate summary. Please try again.")
                else:
                    # Set user preference
                    set_user_language(sender, lang_choice)
                    lang_name = get_language_name(lang_choice)
                    send_whatsapp(sender, f"✅ Language preference set to {lang_name}\n\nNow send a voice message for transcription!")
                return ("", 204)
            
            # Default guidance with smart language hint
            try:
                current_lang = get_user_language(sender)
                lang_name = get_language_name(current_lang)
                from db_multilang import is_user_language_explicitly_set
                
                if is_user_language_explicitly_set(sender):
                    # User has set language preference
                    send_whatsapp(sender, (
                        f"Hi 👋 — I can transcribe voice messages in {lang_name}.\n\n"
                        "🎙️ Send a voice note for meeting minutes\n"
                        "🌐 Type 'language' to change language"
                    ))
                else:
                    # User hasn't set language - show smart guidance
                    send_whatsapp(sender, (
                        "Hi 👋 — I can transcribe voice messages in multiple Indian languages!\n\n"
                        "🎙️ Send a voice note for meeting minutes\n"
                        "🌐 Type 'language' to choose your preferred language\n\n"
                        "*Smart Detection*: I'll auto-detect your language if not set!"
                    ))
            except Exception as e:
                debug_print("Failed to send guidance reply:", e)
            return ("", 204)

        # download media to local file
        local_path = download_media_to_local(media_url)

        # compute duration using mutagen
        duration_seconds = get_audio_duration_seconds(local_path)
        minutes = round(duration_seconds / 60.0, 2)

        # Now perform an atomic reservation: lock user row, check credits/subscription, deduct and insert meeting row
        with get_conn() as conn, conn.cursor() as cur:
            phone = sender
            # lock user row to avoid race conditions
            cur.execute("SELECT credits_remaining, subscription_active, subscription_expiry FROM users WHERE phone=%s FOR UPDATE", (phone,))
            row = cur.fetchone()
            if row:
                credits_remaining = float(row[0]) if row[0] is not None else 0.0
                sub_active = bool(row[1])
                sub_expiry = row[2]
            else:
                # create user if missing
                cur.execute("""
                    INSERT INTO users (phone, credits_remaining, subscription_active, preferred_language, created_at)
                    VALUES (%s, %s, %s, %s, now())
                    RETURNING credits_remaining, subscription_active, subscription_expiry
                """, (phone, 30.0, False, 'hi'))
                newr = cur.fetchone()
                if newr is None:
                    credits_remaining = 30.0
                    sub_active = False
                    sub_expiry = None
                else:
                    if hasattr(newr, "get"):
                        credits_remaining = float(newr.get("credits_remaining") or 0.0)
                        sub_active = bool(newr.get("subscription_active") or False)
                        sub_expiry = newr.get("subscription_expiry")
                    else:
                        credits_remaining = float(newr[0] or 0.0)
                        sub_active = bool(newr[1])
                        sub_expiry = newr[2]

            # If subscription active and not expired → do not deduct
            from datetime import datetime as dt, timezone
            now = dt.now(timezone.utc)
            if sub_active and (sub_expiry is None or sub_expiry > now):
                to_deduct = 0.0
            else:
                to_deduct = minutes

            if to_deduct > 0 and credits_remaining < to_deduct:
                # Not enough credits: create Razorpay payment link and send it
                conn.rollback()
                try:
                    SUBSCRIPTION_PRICE_RUPEES = float(os.getenv("SUBSCRIPTION_PRICE_RUPEES", "499.0"))
                    payment = create_payment_link_for_phone(phone, SUBSCRIPTION_PRICE_RUPEES)
                    order_id = payment.get("order_id") or payment.get("order", {}).get("id")
                    if payment and payment.get("order"):
                        url = payment.get("order").get("short_url") if payment.get("order").get("short_url") else f"{os.getenv('PLATFORM_URL','')}/pay?order_id={order_id}"
                    else:
                        url = f"{os.getenv('PLATFORM_URL','')}/pay?order_id={order_id}"

                    send_whatsapp(phone, (
                        "⚠️ You don't have enough free minutes to transcribe this audio. "
                        "Top up to continue — follow this secure payment link:\n\n" + url
                    ))
                except Exception as e:
                    debug_print("Failed to create/send payment link:", e, traceback.format_exc())
                    send_whatsapp(phone, "⚠️ You have insufficient free minutes. Please visit the app to subscribe.")
                return ("", 204)
                
            # Insert meeting row with message_sid = dedupe_key
            cur.execute("""
                INSERT INTO meeting_notes (phone, audio_file, transcript, summary, message_sid, created_at)
                VALUES (%s, %s, %s, %s, %s, now())
                RETURNING id
            """, (phone, media_url, None, None, dedupe_key))
            new_row = cur.fetchone()
            if not new_row:
                conn.rollback()
                raise RuntimeError("Failed to insert meeting_notes row (no row returned)")
            if hasattr(new_row, "get"):
                meeting_id = new_row.get("id")
            else:
                meeting_id = new_row[0]
            if meeting_id is None:
                conn.rollback()
                raise RuntimeError("Failed to read meeting id after insert")
            conn.commit()

            # Send payment link if balance is zero
            try:
                from db import get_user_credits
                credits_remaining = get_user_credits(phone)
            except Exception:
                credits_remaining = None

            if credits_remaining is not None and credits_remaining <= 0.0:
                amount = float(os.getenv("SUBSCRIPTION_PRICE_RUPEES", "499.0"))
                payment = create_payment_link_for_phone(phone, amount)
                url = payment.get("order", {}).get("short_url") or f"{os.getenv('PLATFORM_URL','')}/pay?order_id={payment.get('order', {}).get('id')}"
                send_whatsapp(phone, f"ℹ️ You've used your free minutes. Top up here: {url}")

        # Cleanup local file after getting duration
        try:
            if local_path and os.path.exists(local_path):
                os.remove(local_path)
        except Exception as e:
            debug_print(f"Failed to cleanup temp file {local_path}:", e)

        # --- ENQUEUE MULTILANG JOB ---
        try:
            from redis_optimizer import get_optimized_queue
            opt_queue = get_optimized_queue()
            
            debug_print(f"About to enqueue multilang job for meeting_id={meeting_id}, media_url={media_url}")
            job = opt_queue.enqueue_job(
                "worker_multilang.process_audio_job_multilang",
                meeting_id,
                media_url
            )
            if job:
                debug_print(f"✅ Successfully enqueued multilang job for meeting_id={meeting_id}")
                current_lang = get_user_language(sender)
                lang_name = get_language_name(current_lang)
                from db_multilang import is_user_language_explicitly_set
                
                send_whatsapp(phone, "🎙️ Processing your audio with smart language detection... I'll ask you to choose summary language shortly!")
            else:
                raise Exception("Job enqueue returned None")
        except Exception as e:
            debug_print("❌ Failed to enqueue multilang job:", e, traceback.format_exc())
            try:
                send_whatsapp(phone, "⚠️ We couldn't start processing your audio. Please try again.")
            except Exception:
                pass

        return ("", 204)

    except Exception as e:
        print("ERROR processing multilang webhook:", e, traceback.format_exc())
        return ("", 204)

# ----------------------------------
# Razorpay webhook (idempotent) - SAME AS ORIGINAL
# ----------------------------------
@app.route("/razorpay-webhook-multilang", methods=["POST"])
def razorpay_webhook_multilang():
    """Razorpay webhook endpoint (production-safe)."""
    raw_bytes = request.get_data()
    signature_hdr = request.headers.get("X-Razorpay-Signature", "") or request.headers.get("x-razorpay-signature", "")

    debug_print("DEBUG — razorpay webhook received, signature header:", signature_hdr)
    debug_print("DEBUG — raw body (first 300 bytes):", raw_bytes[:300])

    try:
        verified = verify_razorpay_webhook(raw_bytes, signature_hdr)
    except Exception as e:
        debug_print("verify_razorpay_webhook raised exception:", e, traceback.format_exc())
        verified = False

    if not verified:
        debug_print("Razorpay webhook signature verification FAILED. Rejecting with 400.")
        return ("Signature verification failed", 400)

    try:
        event_json = request.get_json(force=True)
    except Exception as e:
        debug_print("Invalid Razorpay webhook JSON:", e, traceback.format_exc())
        return ("Invalid JSON", 400)

    try:
        res = handle_webhook_event(event_json)
        debug_print("Razorpay webhook handled:", res)

        status = res.get("status", "").lower()
        if status in ("ignored", "no_payment_entity"):
            return ("", 204)
        if status == "ok":
            return ("OK", 200)

        debug_print("Unhandled handler result (treat as error):", res)
        return (str(res), 500)
    except Exception as e:
        debug_print("Error handling Razorpay webhook:", e, traceback.format_exc())
        return ("Internal error", 500)

# -------------------------
# Admin endpoints - SAME AS ORIGINAL
# -------------------------
@app.route("/admin/user/<path:phone>", methods=["GET"])
def admin_get_user(phone):
    """Simple admin endpoint to view user state."""
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT phone, credits_remaining, subscription_active, subscription_expiry, preferred_language, created_at FROM users WHERE phone=%s", (phone,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "not found"}), 404

            if hasattr(row, "get"):
                user_obj = dict(row)
            else:
                user_obj = {
                    "phone": row[0], "credits_remaining": row[1], "subscription_active": row[2],
                    "subscription_expiry": row[3], "preferred_language": row[4], "created_at": row[5]
                }
            return jsonify({"user": user_obj}), 200
    except Exception as e:
        debug_print("admin_get_user error:", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route("/admin/notes/<path:phone>", methods=["GET"])
def admin_get_notes(phone):
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, audio_file, summary, created_at FROM meeting_notes WHERE phone=%s ORDER BY id DESC LIMIT 50", (phone,))
            rows = cur.fetchall()
            normalized = []
            for r in rows or []:
                if hasattr(r, "get"):
                    normalized.append(dict(r))
                else:
                    normalized.append({"id": r[0], "audio_file": r[1], "summary": r[2], "created_at": r[3]})
            return jsonify({"notes": normalized}), 200
    except Exception as e:
        debug_print("admin_get_notes error:", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500

# -------------------------
# Health check and debug endpoints - SAME AS ORIGINAL
# -------------------------
@app.route("/health-multilang", methods=["GET"])
def health_multilang():
    return jsonify({"status": "ok", "version": "multilang", "languages": 9, "time": datetime.utcnow().isoformat()}), 200

@app.route("/clear-queue-multilang", methods=["GET", "POST"])
def clear_queue_multilang():
    """Clear Redis queue of old jobs"""
    try:
        from rq.registry import FailedJobRegistry, StartedJobRegistry, FinishedJobRegistry
        
        q = get_queue("default")
        cleared_count = len(q)
        q.empty()
        
        failed_registry = FailedJobRegistry(queue=q)
        started_registry = StartedJobRegistry(queue=q)
        finished_registry = FinishedJobRegistry(queue=q)
        
        failed_count = len(failed_registry)
        started_count = len(started_registry)
        finished_count = len(finished_registry)
        
        failed_registry.requeue(*failed_registry.get_job_ids())
        failed_registry.cleanup()
        started_registry.cleanup()
        finished_registry.cleanup()
        
        q.empty()
        
        return jsonify({
            "status": "all queues and registries cleared", 
            "jobs_cleared": cleared_count,
            "failed_cleared": failed_count,
            "started_cleared": started_count,
            "finished_cleared": finished_count
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/debug-queue-multilang", methods=["GET"])
def debug_queue_multilang():
    """Debug endpoint to check queue status"""
    try:
        from rq import Queue
        default_q = get_queue("default")
        transcribe_q = get_queue("transcribe")
        
        return jsonify({
            "redis_url": get_redis_url()[:50] + "..." if get_redis_url() else None,
            "default_queue_length": len(default_q),
            "transcribe_queue_length": len(transcribe_q),
            "default_jobs": [job.id for job in default_q.jobs[:5]],
            "transcribe_jobs": [job.id for job in transcribe_q.jobs[:5]],
            "version": "multilang"
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/test-worker-multilang", methods=["GET", "POST"])
def test_worker_multilang():
    """Test endpoint to enqueue a simple job"""
    try:
        job = queue.enqueue("worker_multilang.test_worker_job")
        return jsonify({
            "status": "job_enqueued",
            "job_id": job.id,
            "queue_name": queue.name,
            "queue_length": len(queue),
            "redis_connected": queue.connection.ping(),
            "message": "Check worker logs for 'TEST WORKER JOB EXECUTED' message",
            "version": "multilang"
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def test_worker_job():
    """Simple test function"""
    print("🧪 TEST MULTILANG WORKER JOB EXECUTED SUCCESSFULLY!")
    return "test_success_multilang"

# -------------------------
# Main run
# -------------------------
if __name__ == "__main__":
    flask_debug = str(os.getenv("FLASK_DEBUG", "0")).lower() in ("1", "true", "yes")
    debug_print("Starting Multilang Flask app (FLASK_DEBUG=%s) on port %s" % (flask_debug, os.getenv("PORT", "5001")))
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5001)), debug=flask_debug)