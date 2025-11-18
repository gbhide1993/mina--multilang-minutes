#!/usr/bin/env python3
"""
Production Multilang Worker - Fixed Version
- Process audio and send menu (no waiting)
- Separate job handles summary generation
"""

import os
import tempfile
import requests
import traceback
import json
import signal
from dotenv import load_dotenv

load_dotenv()

from db import get_conn
from utils import send_whatsapp
from openai_client_multilang import transcribe_file_multilang, summarize_text_multilang
from language_handler_v2 import get_language_menu, get_language_name

class GracefulKiller:
    """Handle SIGTERM for graceful shutdown"""
    def __init__(self):
        self.kill_now = False
        signal.signal(signal.SIGTERM, self._handle_signal)
    
    def _handle_signal(self, signum, frame):
        self.kill_now = True

killer = GracefulKiller()

def _detect_language_from_transcript(transcript):
    """Detect language from transcript text"""
    if not transcript or len(transcript.strip()) < 10:
        return 'en'
    
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
    english_count = sum(1 for word in english_words if word in transcript[:500].lower())
    
    if english_count >= 3:
        return 'en'
    
    return 'hi'  # Default to Hindi

def process_audio_job(meeting_id, media_url):
    """Process audio and send language menu (no waiting)"""
    print(f"🌐 PRODUCTION WORKER: Processing meeting_id={meeting_id}")
    tmp_path = None
    
    try:
        # Get meeting details
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT phone, audio_file FROM meeting_notes WHERE id=%s", (meeting_id,))
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
        
        # Save to temp file with OpenAI-compatible format detection
        content_type = resp.headers.get('Content-Type', '').lower()
        
        # Map content types to OpenAI-supported formats
        if any(x in content_type for x in ['m4a', 'mp4', 'aac']):
            suffix = '.m4a'
        elif 'wav' in content_type:
            suffix = '.wav'
        elif any(x in content_type for x in ['ogg', 'opus']):
            suffix = '.ogg'
        elif 'webm' in content_type:
            suffix = '.webm'
        elif 'flac' in content_type:
            suffix = '.flac'
        else:
            # Default to mp3 for unknown formats
            suffix = '.mp3'
        
        # Enhanced logging for diagnostics
        first_bytes = resp.content[:16] if len(resp.content) >= 16 else resp.content
        print(f"🌐 WORKER: Content-Type: {content_type}, using suffix: {suffix}")
        print(f"🌐 WORKER: First 16 bytes: {first_bytes.hex() if first_bytes else 'empty'}")
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(resp.content)
            tmp_path = tmp.name
            
        # Verify file is not empty and has reasonable size
        file_size = os.path.getsize(tmp_path)
        print(f"🌐 WORKER: Saved audio file: {tmp_path}, size: {file_size} bytes")
        
        if file_size < 100:  # Less than 100 bytes is likely not valid audio
            raise ValueError(f"Audio file too small: {file_size} bytes")
        
        # Proactive transcoding for better compatibility (optional)
        proactive_transcode = os.getenv("PROACTIVE_TRANSCODE", "false").lower() == "true"
        if proactive_transcode and suffix not in ['.wav', '.mp3', '.m4a']:
            print(f"🌐 WORKER: Proactively converting {suffix} to WAV...")
            try:
                import subprocess
                wav_path = tmp_path.replace(suffix, '.wav')
                result = subprocess.run([
                    'ffmpeg', '-i', tmp_path, '-acodec', 'pcm_s16le', 
                    '-ar', '16000', '-ac', '1', wav_path, '-y'
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0 and os.path.exists(wav_path):
                    print(f"🌐 WORKER: Proactive conversion successful: {wav_path}")
                    os.remove(tmp_path)
                    tmp_path = wav_path
                else:
                    print(f"🌐 WORKER: Proactive conversion failed, using original")
            except Exception as conv_error:
                print(f"🌐 WORKER: Proactive conversion error: {conv_error}")
        
        # Transcribe with enhanced error handling
        print(f"🌐 PRODUCTION WORKER: Starting transcription for file: {tmp_path}")
        try:
            # Try transcription with automatic language detection
            transcript = transcribe_file_multilang(tmp_path, language=None)
            print(f"🌐 PRODUCTION WORKER: Transcription complete, length: {len(transcript) if transcript else 0}")
            
            if not transcript or len(transcript.strip()) < 5:
                raise ValueError("Transcription failed or too short")
                
        except Exception as transcribe_error:
            print(f"🌐 PRODUCTION WORKER: Transcription failed: {transcribe_error}")
            
            # Try converting to a more compatible format if transcription fails
            if "Invalid file format" in str(transcribe_error):
                print(f"🌐 WORKER: Attempting format conversion...")
                try:
                    # Convert to WAV format using ffmpeg if available
                    import subprocess
                    wav_path = tmp_path.replace(suffix, '.wav')
                    result = subprocess.run([
                        'ffmpeg', '-i', tmp_path, '-acodec', 'pcm_s16le', 
                        '-ar', '16000', '-ac', '1', wav_path, '-y'
                    ], capture_output=True, text=True, timeout=30)
                    
                    if result.returncode == 0 and os.path.exists(wav_path):
                        print(f"🌐 WORKER: Converted to WAV: {wav_path}")
                        # Clean up original file
                        os.remove(tmp_path)
                        tmp_path = wav_path
                        
                        # Retry transcription with converted file
                        transcript = transcribe_file_multilang(tmp_path, language=None)
                        print(f"🌐 PRODUCTION WORKER: Transcription after conversion complete, length: {len(transcript) if transcript else 0}")
                        
                        if not transcript or len(transcript.strip()) < 5:
                            raise ValueError("Transcription failed after conversion")
                    else:
                        raise transcribe_error
                        
                except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as conv_error:
                    print(f"🌐 WORKER: Format conversion failed: {conv_error}")
                    raise transcribe_error
            else:
                raise
        
        # Detect language
        detected_language = _detect_language_from_transcript(transcript)
        print(f"🌐 PRODUCTION WORKER: Detected language: {detected_language}")
        
        # Calculate duration for credits
        try:
            from mutagen import File as MutagenFile
            mf = MutagenFile(tmp_path)
            if mf and hasattr(mf, 'info') and hasattr(mf.info, 'length'):
                duration_seconds = float(mf.info.length)
            else:
                # Fallback calculation based on file size and bitrate
                duration_seconds = (len(resp.content) * 8) / 80000
            minutes = round(duration_seconds / 60.0, 2)
        except Exception as duration_error:
            print(f"🌐 PRODUCTION WORKER: Duration calculation failed: {duration_error}")
            minutes = 1.0
        
        # Store in separate columns
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE meeting_notes 
                SET transcript=%s, detected_language=%s, job_state=%s
                WHERE id=%s
            """, (transcript, detected_language, 'awaiting_language_choice', meeting_id))
            
            # Deduct credits
            cur.execute("SELECT credits_remaining, subscription_active FROM users WHERE phone=%s", (phone,))
            user_row = cur.fetchone()
            if user_row and not user_row[1]:  # Not subscribed
                new_credits = max(0.0, float(user_row[0] or 0.0) - minutes)
                cur.execute("UPDATE users SET credits_remaining=%s WHERE phone=%s", (new_credits, phone))
            
            conn.commit()
        
        # Send language menu and END JOB
        detected_name = get_language_name(detected_language)
        menu = get_language_menu()
        
        message = f"🎙️ *Audio transcribed!*\n🔍 Detected: *{detected_name}*\n\n📝 *Choose summary language:*\n\n{menu}"
        send_whatsapp(phone, message)
        
        print(f"🌐 WORKER: Language menu sent, job complete")
        return {"success": True, "transcript_ready": True}
        
    except Exception as e:
        print(f"🌐 PRODUCTION WORKER: Error: {e}")
        traceback.print_exc()
        try:
            if 'phone' in locals():
                send_whatsapp(phone, "⚠️ Processing failed. Please try again.")
        except:
            pass
        return {"error": str(e)}
        
    finally:
        # Cleanup
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
                print(f"🌐 WORKER: Cleaned up {tmp_path}")
            except Exception as e:
                print(f"🌐 WORKER: Cleanup failed: {e}")

def complete_summary_job(meeting_id, chosen_language):
    """Generate summary in chosen language"""
    print(f"🌐 COMPLETING SUMMARY: meeting_id={meeting_id}, language={chosen_language}")
    
    try:
        with get_conn() as conn, conn.cursor() as cur:
            # Get transcript and update language choice
            cur.execute("""
                SELECT phone, transcript FROM meeting_notes 
                WHERE id=%s
            """, (meeting_id,))
            row = cur.fetchone()
            
            if not row:
                return {"error": "Meeting not found"}
            
            phone = row[0] if hasattr(row, '__getitem__') else row.phone
            transcript = row[1] if hasattr(row, '__getitem__') else row.transcript
            
            if not transcript:
                return {"error": "No transcript found"}
            
            # Generate summary with error handling
            print(f"🌐 PRODUCTION WORKER: Generating summary in {chosen_language}...")
            try:
                summary = summarize_text_multilang(transcript, chosen_language)
                print(f"🌐 PRODUCTION WORKER: Summary generated, length: {len(summary) if summary else 0}")
                
                if not summary or len(summary.strip()) < 10:
                    raise ValueError("Summary generation failed or too short")
                    
            except Exception as summary_error:
                print(f"🌐 PRODUCTION WORKER: Summary generation failed: {summary_error}")
                raise
            
            # Send summary to user
            lang_name = get_language_name(chosen_language)
            formatted_summary = f"📝 *Meeting Summary ({lang_name}):*\n\n{summary}"
            send_whatsapp(phone, formatted_summary)
            
            # Idempotent final update with timestamp
            cur.execute("""
                UPDATE meeting_notes 
                SET summary=%s, chosen_language=%s, job_state=%s, summary_generated_at=now()
                WHERE id=%s
            """, (summary, chosen_language, 'completed', meeting_id))
            
            conn.commit()
            
        print(f"🌐 WORKER: Summary sent and job completed")
        return {"success": True, "summary_sent": True}
        
    except Exception as e:
        print(f"🌐 PRODUCTION WORKER: Summary generation error: {e}")
        traceback.print_exc()
        try:
            if 'phone' in locals():
                send_whatsapp(phone, "⚠️ Summary generation failed. Please try again.")
        except:
            pass
        return {"error": str(e)}

def test_worker_job():
    print("PRODUCTION MULTILANG WORKER TEST SUCCESS!")
    return "test_success"