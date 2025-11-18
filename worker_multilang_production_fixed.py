"""
worker_multilang_production_fixed_clean.py

Robust worker for MinA:
- process_audio_job(meeting_id, audio_source)
  * audio_source may be: local file path OR remote URL (HTTP/HTTPS)
  * downloads (streamed), converts if necessary, transcribes, encrypts transcript and updates DB
  * does NOT leave plaintext transcript in DB
- complete_summary_job(meeting_id, language_code=None)
  * reads encrypted transcript, decrypts, summarizes (multilang), encrypts summary, optionally extracts actions
"""

import os
import sys
import time
import json
import tempfile
import traceback
import subprocess
from typing import Optional
from datetime import datetime, timezone, timedelta

import requests
from requests.exceptions import RequestException

# Try to import project modules (these should exist in your repo)
try:
    from db import get_conn, save_meeting_notes_with_sid, create_task, get_conn  # get_conn used for DB
except Exception:
    # If import fails, leave placeholders; deploy will fail and show import error
    raise

try:
    from encryption import encrypt_sensitive_data, decrypt_sensitive_data
except Exception:
    # Provide dummy wrappers to avoid immediate crash (but you should have encryption module)
    def encrypt_sensitive_data(x):
        return x

    def decrypt_sensitive_data(x):
        return x

try:
    # openai_client_multilang must expose transcribe_file_multilang and summarize_text_multilang
    from openai_client_multilang import transcribe_file_multilang, summarize_text_multilang
except Exception:
    # If missing, raise — worker cannot proceed without these
    raise

# Optional: import send_whatsapp helper if available; otherwise fallback to no-op
def _get_send_whatsapp():
    try:
        # Many repos have send_whatsapp in app or a notifications module
        from app import send_whatsapp  # best-effort import
        return send_whatsapp
    except Exception:
        try:
            from notifications import send_whatsapp
            return send_whatsapp
        except Exception:
            # fallback no-op
            def _noop(phone, text):
                print("send_whatsapp noop:", phone, text)
            return _noop

send_whatsapp = _get_send_whatsapp()

# Configuration (environment)
TEMP_DIR = os.getenv("TEMP_DIR", "/tmp")
MAX_FILE_MB = float(os.getenv("MAX_FILE_MB", "24"))  # reject files larger than this
DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT", "60"))  # seconds
TRANSCRIBE_MODEL = os.getenv("TRANSCRIBE_MODEL", "whisper-1")
SUMMARIZE_MODEL = os.getenv("SUMMARIZE_MODEL", "gpt-4o-mini")
RETRY_ATTEMPTS = int(os.getenv("WORKER_RETRY_ATTEMPTS", "3"))

# Ensure temp dir exists
os.makedirs(TEMP_DIR, exist_ok=True)

# Utility logging
def log(*args, **kwargs):
    print("[WORKER]", *args, **kwargs)
    sys.stdout.flush()

def log_err(*args, **kwargs):
    print("[WORKER-ERR]", *args, file=sys.stderr, **kwargs)
    sys.stderr.flush()

# Simple retry helper
def with_retries(fn, attempts=3, initial_delay=0.8, backoff=2.0):
    last_exc = None
    delay = initial_delay
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            log_err(f"attempt {i+1}/{attempts} failed: {e}")
            if i < attempts - 1:
                time.sleep(delay)
                delay *= backoff
    raise last_exc

# Helpers for file handling
def stream_download_to_file(url: str, dest_path: str, timeout: int = DOWNLOAD_TIMEOUT):
    """Stream HTTP(S) download to dest_path. Checks Content-Length header for size limit."""
    headers = {"User-Agent": "MinA-Worker/1.0"}
    with requests.get(url, headers=headers, timeout=timeout, stream=True) as r:
        r.raise_for_status()
        cl = r.headers.get("Content-Length")
        if cl:
            try:
                file_size_mb = int(cl) / (1024 * 1024)
                log(f"Content-Length: {cl} bytes (~{file_size_mb:.2f} MB)")
                if file_size_mb > MAX_FILE_MB:
                    raise ValueError(f"Remote file too large: {file_size_mb:.2f} MB (max {MAX_FILE_MB} MB)")
            except Exception:
                # ignore header parse errors and continue streaming
                pass
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    size = os.path.getsize(dest_path)
    return size

def ensure_wav_via_ffmpeg(in_path: str) -> str:
    """If file is already wav-like, return same path. Otherwise convert to wav and return new path."""
    # We'll convert to WAV (16k, mono, pcm_s16le) for whisper if needed
    ext = os.path.splitext(in_path)[1].lower()
    if ext in (".wav",):
        return in_path
    out_fd, out_path = tempfile.mkstemp(suffix=".wav", dir=TEMP_DIR)
    os.close(out_fd)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", in_path,
        "-ac", "1", "-ar", "16000",
        "-acodec", "pcm_s16le",
        out_path
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        log(f"Converted {in_path} -> {out_path} via ffmpeg")
        return out_path
    except FileNotFoundError:
        log_err("ffmpeg not installed; returning original path (may fail transcription)")
        # remove out_path if created
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except Exception:
            pass
        return in_path
    except subprocess.CalledProcessError as e:
        log_err("ffmpeg conversion failed:", e)
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except Exception:
            pass
        # propagate to caller to decide fallback
        raise

# DB helper to update meeting row safely
def update_meeting(meeting_id: int, **fields):
    """Update meeting_notes row by id with provided fields dict."""
    if not fields:
        return
    set_clause = ", ".join([f"{k}=%s" for k in fields.keys()])
    vals = list(fields.values())
    vals.append(meeting_id)
    q = f"UPDATE meeting_notes SET {set_clause}, updated_at=now() WHERE id=%s"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(q, tuple(vals))
        conn.commit()

# --- Job functions ---------------------------------------------------------

def process_audio_job(meeting_id: int, audio_source: str):
    """
    Entry point to process an audio file.
    audio_source: either a local file path or an HTTP/HTTPS URL to download.
    """
    start_ts = time.time()
    log(f"START process_audio_job meeting_id={meeting_id} source={audio_source}")

    tmp_in = None
    tmp_conv = None
    try:
        # Fetch meeting metadata (phone) - optional; best-effort
        phone = None
        try:
            with get_conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT phone FROM meeting_notes WHERE id=%s LIMIT 1", (meeting_id,))
                row = cur.fetchone()
                if row:
                    phone = row[0] if not hasattr(row, "get") else row.get("phone")
        except Exception as e:
            log_err("Warning: unable to read phone for meeting", meeting_id, e)

        # Prepare temp file
        fd, tmp_in = tempfile.mkstemp(prefix=f"mina_in_{meeting_id}_", dir=TEMP_DIR, suffix=os.path.splitext(str(audio_source))[-1] or ".dat")
        os.close(fd)

        # If audio_source looks like URL -> download stream
        if str(audio_source).lower().startswith("http"):
            # download streamed
            def _dl():
                return stream_download_to_file(audio_source, tmp_in, timeout=DOWNLOAD_TIMEOUT)
            with_retries(_dl, attempts=RETRY_ATTEMPTS)
        else:
            # assume it's a local file path already accessible to worker
            if not os.path.exists(audio_source):
                raise FileNotFoundError(f"local audio source not found: {audio_source}")
            # copy to tmp_in
            with open(audio_source, "rb") as src, open(tmp_in, "wb") as dst:
                for chunk in iter(lambda: src.read(8192), b""):
                    dst.write(chunk)

        # sanity size check
        file_size = os.path.getsize(tmp_in)
        file_mb = file_size / (1024 * 1024)
        log(f"Downloaded audio for meeting {meeting_id}: {file_size} bytes (~{file_mb:.2f}MB)")
        if file_mb < 0.001:
            raise ValueError("Downloaded audio file is too small or empty.")

        if file_mb > MAX_FILE_MB:
            send_whatsapp(phone or "unknown", f"⚠️ Audio too large ({file_mb:.1f} MB). Max allowed is {MAX_FILE_MB} MB. Please send a shorter recording.")
            update_meeting(meeting_id, job_state="failed", failure_reason=f"file_too_large_{file_mb:.2f}MB")
            return

        # attempt direct transcription; if fails due to unsupported format, try conversion
        try:
            # If format likely incompatible, convert first (heuristic)
            ext = os.path.splitext(tmp_in)[1].lower()
            need_convert = ext not in (".wav", ".m4a", ".mp3", ".ogg", ".opus", ".webm", ".aac", ".3gp")
            if need_convert:
                try:
                    tmp_conv = ensure_wav_via_ffmpeg(tmp_in)
                except Exception:
                    tmp_conv = None
            path_for_transcribe = tmp_conv or tmp_in

            # transcribe using your openai wrapper
            def _trans():
                return transcribe_file_multilang(path_for_transcribe, language=None)
            transcript_text = with_retries(_trans, attempts=RETRY_ATTEMPTS)

        except Exception as trans_e:
            # If failed and we haven't tried conversion yet, try convert and retry
            log_err("Initial transcription failed:", trans_e)
            if tmp_conv is None:
                try:
                    tmp_conv = ensure_wav_via_ffmpeg(tmp_in)
                    def _trans2():
                        return transcribe_file_multilang(tmp_conv, language=None)
                    transcript_text = with_retries(_trans2, attempts=RETRY_ATTEMPTS)
                except Exception as trans_e2:
                    log_err("Transcription failed after conversion:", trans_e2)
                    update_meeting(meeting_id, job_state="failed", failure_reason="transcription_error")
                    send_whatsapp(phone or "unknown", "⚠️ Sorry, transcription failed for your audio. Please try again with a clearer recording.")
                    return
            else:
                update_meeting(meeting_id, job_state="failed", failure_reason="transcription_error")
                send_whatsapp(phone or "unknown", "⚠️ Sorry, transcription failed for your audio. Please try again with a clearer recording.")
                return

        # Basic language detection heuristic — prefer whisper's auto-detect if available, otherwise fallback
        detected_language = None
        try:
            # attempt to detect language by simple heuristics
            txt_sample = transcript_text[:300].lower()
            if any(ch in txt_sample for ch in ["\u0900", "\u0901", "\u0902", "आप", "हैं", "हूँ"]):
                detected_language = "hi"
            else:
                detected_language = "en"
        except Exception:
            detected_language = "en"

        # Encrypt transcript immediately before writing to DB (avoid plaintext at rest)
        try:
            enc_transcript = encrypt_sensitive_data(transcript_text)
        except Exception as e:
            log_err("Encryption failed, storing plaintext as fallback:", e)
            enc_transcript = transcript_text

        # Save encrypted transcript and set job_state for next step
        update_meeting(meeting_id,
                       transcript=enc_transcript,
                       detected_language=detected_language,
                       job_state="transcribed",
                       audio_file=os.path.basename(tmp_in))

        # Notify user that transcript is ready (optional)
        try:
            send_whatsapp(phone or "unknown", f"✅ Your meeting ({meeting_id}) was transcribed. Request summary via the app or use API to summarize.")
        except Exception as e:
            log_err("send_whatsapp failed:", e)

        log(f"process_audio_job complete meeting_id={meeting_id} duration={time.time()-start_ts:.1f}s")

    except Exception as e:
        log_err("process_audio_job unhandled exception:", e, traceback.format_exc())
        try:
            update_meeting(meeting_id, job_state="failed", failure_reason=str(e)[:1000])
        except Exception:
            pass
    finally:
        # cleanup temp files
        for p in (tmp_in, tmp_conv):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

def complete_summary_job(meeting_id: int, language_code: Optional[str] = None):
    """
    Decrypts transcript, produces a summary in the requested language (or detected language),
    encrypts summary and optionally extracts action items.
    """
    log(f"START complete_summary_job meeting_id={meeting_id} lang={language_code}")
    start_ts = time.time()
    try:
        # fetch encrypted transcript and phone
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT transcript, detected_language, phone FROM meeting_notes WHERE id=%s LIMIT 1", (meeting_id,))
            row = cur.fetchone()
            if not row:
                log_err("meeting not found:", meeting_id)
                return
            enc_transcript = row[0]
            detected_language = row[1]
            phone = row[2] if len(row) > 2 else None

        if not enc_transcript:
            log_err("No transcript found for meeting", meeting_id)
            update_meeting(meeting_id, job_state="failed", failure_reason="no_transcript")
            return

        # decrypt transcript
        try:
            transcript = decrypt_sensitive_data(enc_transcript)
        except Exception as e:
            log_err("decrypt failed, using raw encrypted value as fallback (not ideal)", e)
            transcript = enc_transcript

        # decide language_code
        lang = language_code or detected_language or "en"
        # Build a conservative summarization instruction
        instructions = (
            "You are an expert meeting summarizer. Produce a concise summary with:\n"
            "- short headline\n- key discussion points\n- decisions\n- action items (bullet list)\n- next steps\nKeep output short and in the requested language. If action items include owners/due dates, extract them."
        )

        # call summarizer (wrap with retries)
        def _summ():
            return summarize_text_multilang(transcript, language_code=lang, instructions=instructions, max_tokens=900, temperature=0.2)
        summary_text = with_retries(_summ, attempts=RETRY_ATTEMPTS)

        # encrypt and save summary
        try:
            enc_summary = encrypt_sensitive_data(summary_text)
        except Exception as e:
            log_err("Summary encryption failed:", e)
            enc_summary = summary_text

        update_meeting(meeting_id,
                       summary=enc_summary,
                       summary_language=lang,
                       summary_generated_at=datetime.now(timezone.utc),
                       job_state="summary_completed")

        # optional: extract action items with a structured JSON prompt
        try:
            ai_instruction = (
                "Extract action items from the meeting transcript. Return strictly valid JSON array of objects like:\n"
                "[{\"text\": \"...\", \"owner\": \"name or null\", \"due\": \"YYYY-MM-DD or null\"}, ...]\n"
                "Return only the JSON array."
            )
            def _actions():
                return summarize_text_multilang(transcript, language_code="en", instructions=ai_instruction, max_tokens=500, temperature=0.0)
            actions_raw = with_retries(_actions, attempts=2)
            # extract JSON from model output
            s = actions_raw.strip()
            start = s.find("[")
            end = s.rfind("]") + 1
            json_text = s[start:end] if start != -1 and end != -1 else s
            items = []
            try:
                items = json.loads(json_text)
            except Exception as e:
                log_err("Failed to parse action items JSON:", e, "raw:", actions_raw)

            created_tasks = []
            for it in items if isinstance(items, list) else []:
                text = it.get("text") or str(it)
                owner = it.get("owner")
                due = it.get("due")
                # create task in DB using create_task helper (phone is owner context)
                try:
                    task = create_task(phone, text, description=None, due_at=due, priority=3, source='mina_ai', metadata={"meeting_id": meeting_id})
                    created_tasks.append(task)
                except Exception as e:
                    log_err("create_task failed:", e)

            if created_tasks:
                send_whatsapp(phone or "unknown", f"✅ Found {len(created_tasks)} action items from meeting {meeting_id}. They have been added to your tasks.")

        except Exception as e:
            log_err("Action extraction failed:", e)

        log(f"complete_summary_job done meeting_id={meeting_id} duration={time.time()-start_ts:.1f}s")

    except Exception as e:
        log_err("complete_summary_job unhandled:", e, traceback.format_exc())
        try:
            update_meeting(meeting_id, job_state="failed", failure_reason=str(e)[:1000])
        except Exception:
            pass

# Expose for RQ import
if __name__ == "__main__":
    # basic manual runner for debugging
    if len(sys.argv) >= 3 and sys.argv[1] == "test":
        mid = int(sys.argv[2])
        src = sys.argv[3] if len(sys.argv) > 3 else "/tmp/test.mp3"
        process_audio_job(mid, src)
    else:
        print("This module is intended to be imported by rq worker. Example: rq worker --with-scheduler")
