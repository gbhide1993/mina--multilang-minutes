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
        print(f"⚠️ Missing Twilio credentials. SID: {'✓' if account_sid else '✗'}, Token: {'✓' if auth_token else '✗'}")
        return False
    
    print(f"DEBUG: Using Twilio SID: {account_sid[:10]}...{account_sid[-4:]}")

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
            print(f"❌ Twilio error (attempt {attempt + 1}/{max_retries}): {error_str}")
            
            if "401" in error_str or "Authenticate" in error_str:
                print(f"❌ Authentication failed. Check Twilio credentials.")
                return False
            elif "503" in error_str or "Service is unavailable" in error_str:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2  # 2, 4, 6 seconds
                    print(f"⚠️ Twilio service unavailable. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
            
            if attempt == max_retries - 1:
                print(f"❌ Final attempt failed for {to_phone}: {e}")
                return False
    
    print(f"❌ Failed to send WhatsApp message after {max_retries} attempts")
    return False


def send_whatsapp_document(to_phone: str, content: str, filename: str = "meeting_minutes.txt", caption: str = "", max_retries: int = 3) -> bool:
    """
    Send a text document via WhatsApp using Twilio API.
    
    Args:
        to_phone (str): Recipient's WhatsApp phone number
        content (str): Text content to send as document
        filename (str): Name of the file to send
        caption (str): Optional caption for the document
        max_retries (int): Maximum number of retry attempts
    Returns:
        bool: True on success, False on failure
    """
    import time
    import tempfile
    import requests
    import base64
    
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_whatsapp_number = os.getenv("TWILIO_WHATSAPP_FROM") or os.getenv("TWILIO_FROM") or "whatsapp:+14155238886"

    if not to_phone:
        print("⚠️ send_whatsapp_document called with no recipient phone number.")
        return False

    if not account_sid or not auth_token:
        print("⚠️ Missing Twilio credentials in environment.")
        return False

    to_whatsapp_number = normalize_phone_for_db(to_phone)
    client = TwilioClient(account_sid, auth_token)
    
    # Process document content for WhatsApp
    temp_file_path = None
    try:
        # Create temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name
        
        for attempt in range(max_retries):
            try:
                # For now, send as long message since Twilio media upload requires public URL
                # Split content into chunks if too long
                max_msg_length = 1500
                if len(content) <= max_msg_length:
                    msg = client.messages.create(
                        from_=from_whatsapp_number,
                        body=f"{caption}\n\n{content}",
                        to=to_whatsapp_number
                    )
                else:
                    # Send in chunks
                    chunks = [content[i:i+max_msg_length] for i in range(0, len(content), max_msg_length)]
                    for i, chunk in enumerate(chunks, 1):
                        chunk_caption = f"{caption} (Part {i}/{len(chunks)})" if i == 1 else f"(Part {i}/{len(chunks)})"
                        msg = client.messages.create(
                            from_=from_whatsapp_number,
                            body=f"{chunk_caption}\n\n{chunk}",
                            to=to_whatsapp_number
                        )
                        if i < len(chunks):
                            time.sleep(1)  # Brief delay between chunks
                
                print(f"✅ WhatsApp document content sent to {to_whatsapp_number}")
                return True
                
            except Exception as e:
                error_str = str(e)
                if "503" in error_str or "Service is unavailable" in error_str:
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 2
                        print(f"⚠️ Twilio service unavailable (attempt {attempt + 1}/{max_retries}). Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                
                print(f"❌ Failed to send WhatsApp document to {to_phone}: {e}")
                return False
        
        print(f"❌ Failed to send WhatsApp document after {max_retries} attempts")
        return False
        
    except Exception as e:
        print(f"❌ Error processing document: {e}")
        return False
    finally:
        # Cleanup temporary file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception as e:
                print(f"⚠️ Failed to cleanup temp file {temp_file_path}: {e}")


def create_detailed_meeting_minutes(summary: str, transcript: str, language: str, meeting_date: str = None) -> str:
    """
    Create a comprehensive meeting minutes document with all details.
    
    Args:
        summary (str): Meeting summary
        transcript (str): Full transcript
        language (str): Language name
        meeting_date (str): Meeting date (optional)
    Returns:
        str: Formatted meeting minutes document
    """
    from datetime import datetime
    
    if not meeting_date:
        meeting_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # Create a more WhatsApp-friendly format
    document = f"""📝 *MEETING MINUTES*

📅 *Date:* {meeting_date}
🌍 *Language:* {language}
⚙️ *Generated by:* MinA Meeting Assistant

{'=' * 40}
📝 *SUMMARY*
{'=' * 40}

{summary}

{'=' * 40}
🎤 *FULL TRANSCRIPT*
{'=' * 40}

{transcript}

{'=' * 40}
✅ *END OF DOCUMENT*
{'=' * 40}

📝 This document was automatically generated from audio transcription.
📞 For questions or corrections, please contact the meeting organizer.
"""
    
    return document


def transcribe_file_multilang(file_path: str) -> str:
    """
    Transcribe an audio file into text.
    Placeholder for now – replace internals with your actual STT logic.
    """
    # TODO: plug in Whisper / Google STT / any engine you already use
    # For now, raise explicit error if not implemented
    raise NotImplementedError("transcribe_file_multilang is not implemented yet")
