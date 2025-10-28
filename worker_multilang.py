#!/usr/bin/env python3
"""
Multi-language Worker - Enhanced with smart language detection
Detects language from audio, then asks user for summary language preference
"""

import os
import tempfile
import requests
import traceback
import json
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

from db import get_conn
from utils import send_whatsapp
from openai_client_multilang import transcribe_file_multilang, summarize_text_multilang
from db_multilang import get_user_language

def _detect_language_from_transcript(transcript):
    """Detect language from transcript text"""
    if not transcript or len(transcript.strip()) < 10:
        return None
    
    # Simple language detection based on character patterns and common words
    text_sample = transcript[:500].lower()
    
    # Check for Devanagari script (Hindi/Marathi)
    if any('\u0900' <= char <= '\u097F' for char in transcript):
        # Distinguish Hindi vs Marathi by common words
        marathi_words = ['आहे', 'होते', 'करतो', 'करते', 'मला', 'तुला']
        if any(word in transcript for word in marathi_words):
            return 'mr'
        return 'hi'
    
    # Check for Tamil script
    if any('\u0B80' <= char <= '\u0BFF' for char in transcript):
        return 'ta'
    
    # Check for Telugu script
    if any('\u0C00' <= char <= '\u0C7F' for char in transcript):
        return 'te'
    
    # Check for Bengali script
    if any('\u0980' <= char <= '\u09FF' for char in transcript):
        return 'bn'
    
    # Check for Gujarati script
    if any('\u0A80' <= char <= '\u0AFF' for char in transcript):
        return 'gu'
    
    # Check for Kannada script
    if any('\u0C80' <= char <= '\u0CFF' for char in transcript):
        return 'kn'
    
    # Check for Punjabi script
    if any('\u0A00' <= char <= '\u0A7F' for char in transcript):
        return 'pa'
    
    # Check for English by common English words
    english_words = ['the', 'and', 'is', 'to', 'of', 'in', 'for', 'with', 'on', 'at']
    english_count = sum(1 for word in english_words if word in text_sample)
    
    if english_count >= 3:
        return 'en'
    
    # Default to Hindi if no clear detection
    return 'hi'

def _store_pending_summary_job(meeting_id, phone, transcript, detected_language, minutes):
    """Store job state for continuation after language selection"""
    job_data = {
        'meeting_id': meeting_id,
        'phone': phone,
        'transcript': transcript,
        'detected_language': detected_language,
        'minutes': minutes,
        'status': 'awaiting_language_selection'
    }
    
    # Store in database as JSON
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE meeting_notes 
            SET summary = %s 
            WHERE id = %s
        """, (json.dumps(job_data), meeting_id))
        conn.commit()

def _parse_summary_sections(summary_text):
    """Extract different sections from summary"""
    sections = {'discussion': '', 'actions': '', 'decisions': ''}
    
    lines = summary_text.split('\n')
    current_section = 'discussion'
    
    for line in lines:
        line_lower = line.lower().strip()
        
        if any(keyword in line_lower for keyword in ['action item', 'next step', 'follow up', 'todo', 'task']):
            current_section = 'actions'
        elif any(keyword in line_lower for keyword in ['decision', 'conclusion', 'resolution']):
            current_section = 'decisions'
        elif line.startswith('#') or line.startswith('**'):
            if 'action' not in line_lower and 'decision' not in line_lower:
                current_section = 'discussion'
        
        if line.strip():
            sections[current_section] += line + '\n'
    
    for key in sections:
        sections[key] = sections[key].strip()
    
    return sections

def _split_actions_intelligently(actions_text, max_chars):
    """Split action items without breaking individual items"""
    parts = []
    current_part = ''
    
    items = []
    for line in actions_text.split('\n'):
        if line.strip().startswith(('•', '-', '*')) or line.strip()[0:2].replace('.', '').isdigit():
            if current_part:
                items.append(current_part.strip())
            current_part = line
        else:
            current_part += '\n' + line
    
    if current_part:
        items.append(current_part.strip())
    
    current_part = ''
    for item in items:
        if len(current_part + '\n\n' + item) > max_chars and current_part:
            parts.append(current_part.strip())
            current_part = item
        else:
            current_part += ('\n\n' if current_part else '') + item
    
    if current_part:
        parts.append(current_part.strip())
    
    return parts if parts else [actions_text[:max_chars]]

def process_audio_job_multilang(meeting_id, media_url):
    """Enhanced multilang worker - detects language then asks for summary preference"""
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
        
        # Smart transcription with auto-detection
        print(f"🌐 MULTILANG WORKER: Starting smart transcription...")
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
        
        # Update database with transcript only
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE meeting_notes SET transcript=%s WHERE id=%s", (transcript, meeting_id))
                
                # Deduct credits
                cur.execute("SELECT credits_remaining, subscription_active FROM users WHERE phone=%s", (phone,))
                user_row = cur.fetchone()
                if user_row and not user_row[1]:  # Not subscribed
                    new_credits = max(0.0, float(user_row[0] or 0.0) - minutes)
                    cur.execute("UPDATE users SET credits_remaining=%s WHERE phone=%s", (new_credits, phone))
                
                conn.commit()
        
        # Send smart language selection menu
        from language_handler_v2 import get_language_name, SUPPORTED_LANGUAGES
        detected_lang_name = get_language_name(detected_language) if detected_language else "Unknown"
        
        smart_menu = f"🎙️ *Audio transcribed successfully!*\n"
        smart_menu += f"🔍 Detected language: *{detected_lang_name}*\n\n"
        smart_menu += "📝 *Choose language for summary & action items:*\n\n"
        
        for i, (code, lang) in enumerate(SUPPORTED_LANGUAGES.items(), 1):
            marker = " ✅" if code == detected_language else ""
            smart_menu += f"{i}. {lang['name']}{marker}\n"
        
        smart_menu += "\n🔢 Reply with number (1-9) for summary language"
        
        send_whatsapp(phone, smart_menu)
        
        # Store job state for continuation
        _store_pending_summary_job(meeting_id, phone, transcript, detected_language, minutes)
        
        # Cleanup
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
            
        return {"success": True, "meeting_id": meeting_id, "status": "awaiting_language_selection", "detected_language": detected_language}
        
    except Exception as e:
        print(f"🌐 MULTILANG WORKER: Error: {e}")
        traceback.print_exc()
        if 'phone' in locals():
            send_whatsapp(phone, "⚠️ Processing failed. Please try again.")
        return {"error": str(e)}

def complete_summary_job(meeting_id, summary_language):
    """Complete the summary job after user selects language"""
    print(f"🌐 MULTILANG WORKER: Completing summary for meeting_id={meeting_id} in language={summary_language}")
    
    try:
        # Get stored job data
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT phone, summary FROM meeting_notes WHERE id=%s", (meeting_id,))
            row = cur.fetchone()
            if not row:
                return {"error": "Meeting not found"}
            
            phone = row[0]
            job_data_str = row[1]
            
            try:
                job_data = json.loads(job_data_str)
                transcript = job_data['transcript']
                detected_language = job_data.get('detected_language')
            except:
                return {"error": "Invalid job data"}
        
        # Generate summary in selected language
        summary = summarize_text_multilang(
            transcript, 
            "Create comprehensive meeting minutes with clear sections: 1) Key Discussion Points 2) Important Decisions 3) Action Items with owners 4) Next Steps. Be specific and detailed. Use bullet points and clear formatting.",
            max_tokens=1000,
            temperature=0.1,
            language_code=summary_language
        )
        
        # Update database with final summary
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE meeting_notes SET summary=%s WHERE id=%s", (summary, meeting_id))
            conn.commit()
        
        # Send multi-message summary
        from language_handler_v2 import get_language_name
        lang_name = get_language_name(summary_language)
        
        if summary:
            sections = _parse_summary_sections(summary)
            max_chars = 1400
            import time
            
            # Send discussion
            if sections['discussion']:
                disc_header = f"📝 *Meeting Summary - Discussion ({lang_name})*\n\n"
                available_chars = max_chars - len(disc_header)
                
                if len(sections['discussion']) <= available_chars:
                    msg1 = disc_header + sections['discussion']
                else:
                    msg1 = disc_header + sections['discussion'][:available_chars-15] + "\n\n...(continued)"
                
                send_whatsapp(phone, msg1)
                time.sleep(2)
            
            # Send action items
            if sections['actions']:
                action_header = f"✅ *Action Items & Next Steps ({lang_name})*\n\n"
                available_chars = max_chars - len(action_header)
                
                if len(sections['actions']) <= available_chars:
                    action_msg = action_header + sections['actions']
                    send_whatsapp(phone, action_msg)
                else:
                    action_parts = _split_actions_intelligently(sections['actions'], available_chars)
                    for i, part in enumerate(action_parts, 1):
                        part_header = f"✅ *Action Items - Part {i} ({lang_name})*\n\n"
                        msg = part_header + part
                        if len(msg) > max_chars:
                            part = part[:max_chars - len(part_header) - 10] + "..."
                            msg = part_header + part
                        send_whatsapp(phone, msg)
                        if i < len(action_parts):
                            time.sleep(2)
        
        return {"success": True, "meeting_id": meeting_id, "summary_language": summary_language}
        
    except Exception as e:
        print(f"🌐 MULTILANG WORKER: Summary completion error: {e}")
        return {"error": str(e)}

def test_worker_job():
    """Simple test function for multilang worker"""
    print("🧪 TEST MULTILANG WORKER JOB EXECUTED SUCCESSFULLY!")
    return "test_success_multilang"
