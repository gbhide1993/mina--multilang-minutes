# app.py - Multi-language WhatsApp Meeting Minutes App
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
TEST_MODE = os.getenv("TEST_MODE", "0") == "1"
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

def download_file(url, fallback_ext=".m4a"):
    """Download the media URL to a temporary file. Preserve extension based on Content-Type header if possible. Returns local path."""
    try:
        resp = requests.get(url, stream=True, timeout=60)
        resp.raise_for_status()
    except Exception as e:
        debug_print("download_file: request failed:", e)
        raise

    ct = resp.headers.get("Content-Type", "")
    ext = _ext_from_content_type(ct)
    if not ext:
        path = unquote(urlparse(url).path)
        guessed = os.path.splitext(path)[1]
        ext = guessed if guessed else fallback_ext

    fname = f"incoming_{int(time.time())}{ext}"
    tmp_path = os.path.join(TEMP_DIR, fname)

    try:
        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    except Exception as e:
        debug_print("download_file: writing file failed:", e)
        raise

    debug_print(f"Downloading media from: {url}")
    debug_print(f"Saved media to: {tmp_path}  (Content-Type: {ct}, ext used: {ext})")
    return tmp_path

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

def format_minutes_for_whatsapp(result: dict) -> str:
    """Turn the structured result into a WhatsApp-friendly text reply (not JSON)."""
    summary = result.get("summary", "").strip()
    bullets = result.get("bullets", []) or []
    participants = result.get("participants", []) or []

    out = []
    if summary:
        out.append("*Summary*\n" + summary)
    if participants:
        p = ", ".join(participants) if isinstance(participants, list) else str(participants)
        out.append(f"*Participants*: {p}")
    if bullets:
        out.append("*Key Points / Action Items*")
        for b in bullets:
            out.append(f"• {b}")
    return "\n\n".join(out).strip()

def compute_audio_duration_seconds(file_path):
    """Compute audio duration safely using Mutagen."""
    try:
        audio = MutagenFile(file_path)
        if not audio or not getattr(audio.info, 'length', None):
            return 0.0
        return round(audio.info.length, 2)
    except Exception as e:
        print("⚠️ Could not compute duration:", e)
        return 0.0

def format_summary_for_whatsapp(summary_text):
    """Make the summary WhatsApp-friendly (bold, emoji, bullet formatting)."""
    formatted = re.sub(r"^- ", "• ", summary_text, flags=re.MULTILINE)
    header = "📝 *Meeting Summary:*\n\n"
    return header + formatted.strip()

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

@app.route("/twilio-webhook", methods=["POST"])
def twilio_webhook():
    """Multi-language webhook handler with ALL original features"""
    from datetime import datetime as dt
    print(f"📞 WEBHOOK: Received request from {request.remote_addr} at {dt.utcnow()}")
    print(f"📞 WEBHOOK: Headers: {dict(request.headers)}")
    print(f"📞 WEBHOOK: Form data: {dict(request.form)}")
    
    try:
        sender_raw = request.values.get("From") or request.form.get("From")
        sender = normalize_phone_for_db(sender_raw)
        message_sid = request.values.get("MessageSid") or request.form.get("MessageSid")
        media_url = request.values.get("MediaUrl0") or request.form.get("MediaUrl0")
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
            # Check if user has pending summary job first
            pending_job = _get_pending_summary_job(sender)
            
            # Language choice for pending summary
            lang_choice = parse_language_choice(body_text)
            if lang_choice and pending_job:
                # Complete pending summary with selected language
                try:
                    # Enqueue completion job
                    if queue:
                        job = queue.enqueue(
                            "worker_multilang.complete_summary_job",
                            pending_job['meeting_id'],
                            lang_choice,
                            job_timeout=60 * 60
                        )
                        if job:
                            lang_name = get_language_name(lang_choice)
                            send_whatsapp(sender, f"🔄 Generating summary in {lang_name}...")
                            debug_print(f"✅ Enqueued summary completion for meeting {pending_job['meeting_id']} in {lang_name}")
                        else:
                            send_whatsapp(sender, "⚠️ Failed to process request. Please try again.")
                    else:
                        send_whatsapp(sender, "⚠️ Service unavailable. Please try again later.")
                except Exception as e:
                    debug_print(f"Error enqueuing summary completion: {e}")
                    send_whatsapp(sender, "⚠️ Failed to generate summary. Please try again.")
                return ("", 204)
            
            # Language menu request
            if body_text.lower() in ['language', 'lang', 'settings', 'भाषा', 'ভাষা']:
                if pending_job:
                    # Show language menu for pending summary
                    detected_lang = pending_job.get('detected_language', 'en')
                    detected_name = get_language_name(detected_lang)
                    menu = get_language_menu()
                    send_whatsapp(sender, f"🎙️ *Audio transcribed!*\n🔍 Detected: *{detected_name}*\n\n{menu}")
                else:
                    # Show regular language menu
                    menu = get_language_menu()
                    send_whatsapp(sender, menu)
                return ("", 204)
            
            # Set user language preference (when no pending job)
            if lang_choice and not pending_job:
                set_user_language(sender, lang_choice)
                lang_name = get_language_name(lang_choice)
                send_whatsapp(sender, f"✅ Language set to {lang_name}\n\nNow send a voice message for transcription!")
                return ("", 204)
            
            # Default guidance message
            if pending_job:
                # Remind user to select language for pending summary
                detected_lang = pending_job.get('detected_language', 'en')
                detected_name = get_language_name(detected_lang)
                menu = get_language_menu()
                send_whatsapp(sender, f"⏳ *Waiting for your choice*\n🔍 Detected: *{detected_name}*\n\n{menu}")
            else:
                # Regular guidance
                send_whatsapp(sender, (
                    "Hi 👋 — Send a voice message and I'll create meeting minutes!\n\n"
                    "🎙️ Send voice note → Choose summary language → Get results\n"
                    "🌐 Type 'language' to see supported languages"
                ))
            return ("", 204)

        # Download media to local file
        local_path = download_media_to_local(media_url)
        if not local_path:
            send_whatsapp(sender, "⚠️ Failed to download audio. Please try again.")
            return ("", 204)

        # Compute duration using mutagen
        duration_seconds = get_audio_duration_seconds(local_path)
        minutes = round(duration_seconds / 60.0, 2)

        # Atomic reservation: lock user row, check credits/subscription, deduct and insert meeting row
        with get_conn() as conn, conn.cursor() as cur:
            phone = sender
            # Lock user row to avoid race conditions
            cur.execute("SELECT credits_remaining, subscription_active, subscription_expiry FROM users WHERE phone=%s FOR UPDATE", (phone,))
            row = cur.fetchone()
            if row:
                credits_remaining = float(row[0]) if row[0] is not None else 0.0
                sub_active = bool(row[1])
                sub_expiry = row[2]
            else:
                # Create user if missing
                cur.execute("""
                    INSERT INTO users (phone, credits_remaining, subscription_active, created_at)
                    VALUES (%s, %s, %s, now())
                    RETURNING credits_remaining, subscription_active, subscription_expiry
                """, (phone, 30.0, False))
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

            # Check subscription status
            from datetime import datetime as dt, timezone
            now = dt.now(timezone.utc)
            if sub_active and (sub_expiry is None or sub_expiry > now):
                to_deduct = 0.0
            else:
                to_deduct = minutes

            if to_deduct > 0 and credits_remaining < to_deduct:
                # Not enough credits: create payment link
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
                    debug_print("Failed to create/send payment link:", e)
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
                raise RuntimeError("Failed to insert meeting_notes row")
            if hasattr(new_row, "get"):
                meeting_id = new_row.get("id")
            else:
                meeting_id = new_row[0]
            if meeting_id is None:
                conn.rollback()
                raise RuntimeError("Failed to read meeting id after insert")
            conn.commit()

        # Cleanup local file
        try:
            if local_path and os.path.exists(local_path):
                os.remove(local_path)
        except Exception as e:
            debug_print(f"Failed to cleanup temp file {local_path}:", e)

        # Enqueue job using correct worker function
        try:
            if queue:
                job = queue.enqueue(
                    "worker_multilang.process_audio_job_multilang",
                    meeting_id,
                    media_url,
                    job_timeout=60 * 60,
                    result_ttl=60 * 60
                )
                if job:
                    debug_print(f"✅ Successfully enqueued job {job.id} for meeting_id={meeting_id}")
                    send_whatsapp(phone, "🎙️ Processing your audio... I'll send the summary shortly!")
                else:
                    raise Exception("Job enqueue returned None")
            else:
                raise Exception("Queue not initialized")
        except Exception as e:
            debug_print("❌ Failed to enqueue job:", e)
            try:
                send_whatsapp(phone, "⚠️ We couldn't start processing your audio. Please try again.")
            except Exception:
                pass

        return ("", 204)

    except Exception as e:
        print("ERROR processing twilio webhook:", e, traceback.format_exc())
        return ("", 204)


@app.route("/razorpay-webhook", methods=["POST"])
def razorpay_webhook():
    """Razorpay webhook endpoint (production-safe)"""
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


@app.route("/admin/user/<path:phone>", methods=["GET"])
def admin_get_user(phone):
    """Admin endpoint to view user state"""
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT phone, credits_remaining, subscription_active, subscription_expiry, created_at FROM users WHERE phone=%s", (phone,))
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "not found"}), 404

            if hasattr(row, "get"):
                user_obj = dict(row)
            else:
                user_obj = {
                    "phone": row[0],
                    "credits_remaining": row[1],
                    "subscription_active": row[2],
                    "subscription_expiry": row[3],
                    "created_at": row[4]
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
                    normalized.append({
                        "id": r[0],
                        "audio_file": r[1],
                        "summary": r[2],
                        "created_at": r[3]
                    })
            return jsonify({"notes": normalized}), 200
    except Exception as e:
        debug_print("admin_get_notes error:", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()}), 200


@app.route("/clear-queue", methods=["GET", "POST"])
def clear_queue():
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


@app.route("/debug-queue", methods=["GET"])
def debug_queue():
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
            "transcribe_jobs": [job.id for job in transcribe_q.jobs[:5]]
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/test-worker", methods=["GET", "POST"])
def test_worker():
    """Test endpoint to enqueue a simple job"""
    try:
        job = queue.enqueue("worker_tasks_v2_enhanced.test_worker_job")
        return jsonify({
            "status": "job_enqueued",
            "job_id": job.id,
            "queue_name": queue.name,
            "queue_length": len(queue),
            "redis_connected": queue.connection.ping(),
            "message": "Check worker logs for 'TEST WORKER JOB EXECUTED' message"
        }), 200
        return jsonify({
            "status": "job_enqueued",
            "job_id": job.id,
            "queue_name": queue.name,
            "queue_length": len(queue),
            "redis_connected": queue.connection.ping(),
            "message": "Check worker logs for 'TEST MULTILANG WORKER JOB EXECUTED' message"
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/test-whatsapp", methods=["POST"])
def test_whatsapp():
    """Test endpoint to simulate WhatsApp webhook with dummy audio"""
    try:
        test_payload = {
            "From": "whatsapp:+1234567890",
            "MessageSid": f"test_msg_{int(time.time())}",
            "MediaUrl0": "https://www.soundjay.com/misc/sounds/bell-ringing-05.wav",
            "Body": ""
        }
        
        with app.test_request_context('/twilio-webhook', method='POST', data=test_payload):
            response = twilio_webhook()
            
        return jsonify({
            "status": "test_webhook_called",
            "response_code": response[1] if isinstance(response, tuple) else 200,
            "test_payload": test_payload
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    flask_debug = str(os.getenv("FLASK_DEBUG", "0")).lower() in ("1", "true", "yes")
    debug_print("Starting Flask multilang app (FLASK_DEBUG=%s) on port %s" % (flask_debug, os.getenv("PORT", "5000")))
    if TEST_MODE:
        app.run(host="0.0.0.0", port=5000, debug=True)
    else:
        app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=flask_debug)
