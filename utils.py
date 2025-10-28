# utils.py
import re
from datetime import datetime, timezone
import os
from urllib.parse import urlparse, unquote
from twilio.rest import Client as TwilioClient

# Use consistent temp directory
TEMP_DIR = os.getenv("TEMP_DIR", os.getcwd())
os.makedirs(TEMP_DIR, exist_ok=True)


# map common content-types to extensions
_CONTENT_TYPE_TO_EXT = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
    "audio/ogg": ".ogg",
    "audio/webm": ".webm",
    "video/mp4": ".mp4",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/pdf": ".pdf",
}

def get_ext_from_content_type(content_type: str) -> str | None:
    """
    Return a file extension (including the dot) for a Content-Type header,
    or None if unknown.
    Example: 'audio/m4a' -> '.m4a'
    """
    if not content_type:
        return None
    # sometimes content_type has charset like 'audio/mpeg; charset=utf-8'
    ct = content_type.split(";")[0].strip().lower()
    return _CONTENT_TYPE_TO_EXT.get(ct)

def safe_filename_from_url(url: str, fallback_ext: str = ".bin") -> str:
    """
    Build a safe filename from a URL path + extension inference.
    Returns a filename like 'downloaded_abcdef.m4a' or 'downloaded.bin' if unknown.
    """
    if not url:
        # caller should handle None earlier
        return f"downloaded{fallback_ext}"

    try:
        parsed = urlparse(unquote(url))
        basename = os.path.basename(parsed.path) or ""
        # keep only safe chars
        basename = re.sub(r'[^A-Za-z0-9_.-]', '_', basename)
        name, ext = os.path.splitext(basename)
        if ext:
            return f"{name}{ext}"
        # try to infer from query parameters (e.g., ?format=m4a)
        query = parsed.query or ""
        m = re.search(r"(?:format|type)=([a-z0-9]+)", query, flags=re.I)
        if m:
            return f"{name}.{m.group(1)}"
    except Exception:
        pass
    return f"downloaded{fallback_ext}"

def normalize_phone_for_db(raw_phone: str) -> str:
    """
    Normalize any phone number into a consistent format:
      'whatsapp:+<country><number>'
    Works with:
      - 919876543210
      - +919876543210
      - whatsapp:+919876543210
      - 09876543210
    """
    if not raw_phone:
        return raw_phone
    p = raw_phone.strip()

    # If already has whatsapp prefix
    if p.startswith("whatsapp:"):
        return p

    # Remove spaces and dashes
    p = p.replace(" ", "").replace("-", "")

    # Extract digits and keep leading +
    if p.startswith("+"):
        digits = p[1:]
    elif p.startswith("00") and p[2:].isdigit():
        digits = p[2:]
    elif p.isdigit():
        digits = p
    else:
        digits = re.sub(r"\D", "", p)

    return f"whatsapp:+{digits}"

def now_utc():
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)

def compute_audio_duration_seconds(file_path):
    """Compute audio duration safely using Mutagen."""
    try:
        from mutagen import File as MutagenFile
        audio = MutagenFile(file_path)
        if not audio or not getattr(audio.info, 'length', None):
            return 0.0
        return round(audio.info.length, 2)
    except Exception as e:
        print("⚠️ Could not compute duration:", e)
        return 0.0



def send_whatsapp(to_phone: str, message: str, max_retries: int = 3) -> bool:
    """
    Send a WhatsApp message using Twilio API with retry logic.

    Args:
        to_phone (str): Recipient's WhatsApp phone number (e.g. +919876543210)
        message (str): Text message to send
        max_retries (int): Maximum number of retry attempts
    Returns:
        bool: True on success, False on failure
    """
    import time
    
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_whatsapp_number = os.getenv("TWILIO_WHATSAPP_FROM") or os.getenv("TWILIO_FROM") or "whatsapp:+14155238886"

    if not to_phone:
        print("⚠️ send_whatsapp called with no recipient phone number. Message not sent.")
        return False

    if not account_sid or not auth_token:
        print("⚠️ Missing Twilio credentials in environment.")
        return False

    to_whatsapp_number = normalize_phone_for_db(to_phone)
    client = TwilioClient(account_sid, auth_token)

    for attempt in range(max_retries):
        try:
            msg = client.messages.create(
                from_=from_whatsapp_number,
                body=message,
                to=to_whatsapp_number
            )
            print(f"✅ WhatsApp message sent to {to_whatsapp_number}, SID: {msg.sid}")
            return True
            
        except Exception as e:
            error_str = str(e)
            if "503" in error_str or "Service is unavailable" in error_str:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2  # 2, 4, 6 seconds
                    print(f"⚠️ Twilio service unavailable (attempt {attempt + 1}/{max_retries}). Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
            
            print(f"❌ Failed to send WhatsApp message to {to_phone}: {e}")
            return False
    
    print(f"❌ Failed to send WhatsApp message after {max_retries} attempts")
    return False
