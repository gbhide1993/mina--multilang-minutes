#!/usr/bin/env python3
"""
Multi-language Worker - 2-Step Flow
1. Transcribe audio + detect language + ask user for summary language
2. Generate summary in user's chosen language
"""

import os
import tempfile
import requests
import traceback
import json
from dotenv import load_dotenv

load_dotenv()

from db import get_conn
from utils import send_whatsapp
from openai_client_multilang import transcribe_file_multilang, summarize_text_multilang
from language_handler_v2 import get_language_menu, get_language_name

def _detect_language_from_transcript(transcript):
    """Detect language from transcript text"""
    if not transcript or len(transcript.strip()) < 10:
        return 'en'
    
    text_sample = transcript[:500].lower()
    
    # Check for Devanagari script (Hindi/Marathi)
    if any('\u0900' <= char <= '\u097F' for char in transcript):
        marathi_words = ['आहे', 'होते', 'करतो', 'करते', 'मला', 'तुला']
        if any(word in transcript for word in marathi_words):
            return 'mr'
        return 'hi'
    
    # Check for other scripts
    if any('\u0B80' <= char <= '\u0BFF' for char in transcript):
        return 'ta'
    if any('\u0C00' <= char <= '\u0C7F' for char in transcript):
        return 'te'
    if any('\u0980' <= char <= '\u09FF' for char in transcript):
        return 'bn'
    if any('\u0A80' <= char <= '\u0AFF' for char in transcript):
        return 'gu'
    if any('\u0C80' <= char <= '\u0CFF' for char in transcript):
        return 'kn'
    if any('\u0A00' <= char <= '\u0A7F' for char in transcript):
        return 'pa'
    
    # Check for English
    english_words = ['the', 'and', 'is', 'to', 'of', 'in', 'for', 'with', 'on', 'at']
    english_count = sum(1 for word in english_words if word in text_sample)
    
    if english_count >= 3:
        return 'en'
    
    return 'hi'  # Default to Hindi

def process_audio_job_multilang(meeting_id, media_url):
    """Step 1: Transcribe audio, detect language, ask user for summary language"""
    print(f"🌐 MULTILANG WORKER: Starting process_audio_job_multilang for meeting_id={meeting_id}")
    try:
        # Get meeting details
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT phone, audio_file, message_sid FROM meeting_notes WHERE id=%s", (meeting_id,))
            row = cur.fetchone()
            if not row:
                return {"error": "Meeting not found"}
            
            phone = row[0] if hasattr(row, '__getitem__') else row.phone
            audio_url = media_url or (row[1] if hasattr(row, '__getitem__') else row.audio_file)
        
        # Download audio
        auth = None
        twilio_sid = os.getenv("TWILIO_ACCOUNT_SID")
        twilio_token = os.getenv("TWILIO_AUTH_TOKEN")
        if "twilio.com" in audio_url and twilio_sid and twilio_token:
            auth = (twilio_sid, twilio_token)
        
        resp = requests.get(audio_url, auth=auth, timeout=60)
        resp.raise_for_status()
        
        # Check file size
        file_size_mb = len(resp.content) / (1024 * 1024)
        if file_size_mb > 24:
            raise ValueError(f"Audio file too large: {file_size_mb:.2f}MB (max 25MB)")
        
        # Save to temp file
        content_type = resp.headers.get('Content-Type', '')
        if 'opus' in content_type.lower():
            suffix = '.opus'
        elif 'ogg' in content_type.lower():
            suffix = '.ogg'
        else:
            suffix = '.mp3'
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(resp.content)
            tmp_path = tmp.name
        
        # Transcribe with auto-detection
        print(f"🌐 MULTILANG WORKER: Starting transcription...")
        try:
            transcript = transcribe_file_multilang(tmp_path, language=None)  # Auto-detect
            print(f"🌐 MULTILANG WORKER: Transcription complete, length: {len(transcript) if transcript else 0}")
            
            # Detect language from transcript
            detected_language = _detect_language_from_transcript(transcript)
            print(f"🌐 MULTILANG WORKER: Detected language: {detected_language}")
            
        except Exception as transcribe_error:
            print(f"🌐 MULTILANG WORKER: Transcription failed: {transcribe_error}")
            raise
        
        # Calculate duration for credits
        try:
            from mutagen import File as MutagenFile
            mf = MutagenFile(tmp_path)
            if mf and hasattr(mf, 'info') and hasattr(mf.info, 'length'):
                duration_seconds = float(mf.info.length)
            else:
                duration_seconds = (len(resp.content) * 8) / 80000
            minutes = round(duration_seconds / 60.0, 2)
        except:
            minutes = 1.0
        
        # Store pending job data in database
        pending_job_data = {
            'meeting_id': meeting_id,
            'phone': phone,
            'transcript': transcript,
            'detected_language': detected_language,
            'minutes': minutes,
            'status': 'awaiting_language_selection'
        }
        
        # Update database with transcript and pending job data
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Store transcript and pending job info
                cur.execute("""
                    UPDATE meeting_notes 
                    SET transcript=%s, summary=%s 
                    WHERE id=%s
                """, (transcript, json.dumps(pending_job_data), meeting_id))
                
                # Deduct credits for transcription
                cur.execute("SELECT credits_remaining, subscription_active FROM users WHERE phone=%s", (phone,))
                user_row = cur.fetchone()
                if user_row and not user_row[1]:  # Not subscribed
                    new_credits = max(0.0, float(user_row[0] or 0.0) - minutes)
                    cur.execute("UPDATE users SET credits_remaining=%s WHERE phone=%s", (new_credits, phone))
                
                conn.commit()
        
        # Send language selection menu to user
        detected_lang_name = get_language_name(detected_language)
        menu = get_language_menu()
        
        smart_menu = f"🎙️ *Audio transcribed successfully!*\n"
        smart_menu += f"🔍 Detected language: *{detected_lang_name}*\n\n"
        smart_menu += "📝 *Choose language for summary:*\n\n"
        smart_menu += menu
        
        send_whatsapp(phone, smart_menu)
        print(f"🌐 MULTILANG WORKER: Language selection menu sent to {phone}")
        
        # Cleanup
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except:
            pass
        
        return {"success": True, "status": "awaiting_language_selection", "meeting_id": meeting_id}
        
    except Exception as e:
        print(f"🌐 MULTILANG WORKER: Error: {e}")
        traceback.print_exc()
        try:
            if 'phone' in locals():
                send_whatsapp(phone, "⚠️ Processing failed. Please try again.")
        except:
            pass
        return {"error": str(e)}

def complete_summary_job(meeting_id, chosen_language):
    """Step 2: Generate summary in user's chosen language"""
    print(f"🌐 MULTILANG WORKER: Completing summary for meeting_id={meeting_id} in language={chosen_language}")
    try:
        # Get pending job data
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT phone, transcript, summary FROM meeting_notes WHERE id=%s", (meeting_id,))
            row = cur.fetchone()
            if not row:
                return {"error": "Meeting not found"}
            
            phone = row[0] if hasattr(row, '__getitem__') else row.phone
            transcript = row[1] if hasattr(row, '__getitem__') else row.transcript
            summary_json = row[2] if hasattr(row, '__getitem__') else row.summary
            
            # Parse pending job data
            try:
                job_data = json.loads(summary_json)
                if job_data.get('status') != 'awaiting_language_selection':
                    return {"error": "No pending job found"}
            except:
                return {"error": "Invalid job data"}
        
        # Generate summary in chosen language
        print(f"🌐 MULTILANG WORKER: Generating summary in {chosen_language}...")
        if chosen_language != 'en':
            summary = summarize_text_multilang(transcript, chosen_language)
        else:
            from openai_client import summarize_text
            summary = summarize_text(transcript, "Create comprehensive meeting minutes with key points and action items.")
        
        print(f"🌐 MULTILANG WORKER: Summary generated, length: {len(summary) if summary else 0}")
        
        # Update database with final summary
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE meeting_notes SET summary=%s WHERE id=%s", (summary, meeting_id))
            conn.commit()
        
        # Send summary to user
        lang_name = get_language_name(chosen_language)
        header = f"📝 *Meeting Summary ({lang_name}):*\n\n"
        send_whatsapp(phone, header + summary)
        
        print(f"🌐 MULTILANG WORKER: Summary sent to {phone} in {lang_name}")
        
        return {"success": True, "meeting_id": meeting_id, "language": chosen_language}
        
    except Exception as e:
        print(f"🌐 MULTILANG WORKER: Error completing summary: {e}")
        traceback.print_exc()
        try:
            if 'phone' in locals():
                send_whatsapp(phone, "⚠️ Failed to generate summary. Please try again.")
        except:
            pass
        return {"error": str(e)}

def test_worker_job():
    """Simple test function"""
    print("🧪 TEST MULTILANG WORKER JOB EXECUTED SUCCESSFULLY!")
    return "test_success"
