#!/usr/bin/env python3
"""
VERSION 2 - Enhanced with Two-Message Summary Feature
Standalone worker tasks for RQ processing with split messaging
"""

import os
import tempfile
import requests
import traceback
from db import get_conn
from utils import send_whatsapp
from openai_client import transcribe_file, summarize_text

def _parse_summary_sections(summary_text):
    """Extract different sections from summary"""
    sections = {'discussion': '', 'actions': '', 'decisions': ''}
    
    # Split by common section headers
    lines = summary_text.split('\n')
    current_section = 'discussion'
    
    for line in lines:
        line_lower = line.lower().strip()
        
        # Detect action items section
        if any(keyword in line_lower for keyword in ['action item', 'next step', 'follow up', 'todo', 'task']):
            current_section = 'actions'
        # Detect decisions section  
        elif any(keyword in line_lower for keyword in ['decision', 'conclusion', 'resolution']):
            current_section = 'decisions'
        # Back to discussion for other headers
        elif line.startswith('#') or line.startswith('**'):
            if 'action' not in line_lower and 'decision' not in line_lower:
                current_section = 'discussion'
        
        # Add line to appropriate section
        if line.strip():
            sections[current_section] += line + '\n'
    
    # Clean up sections
    for key in sections:
        sections[key] = sections[key].strip()
    
    return sections

def _split_actions_intelligently(actions_text, max_chars):
    """Split action items without breaking individual items"""
    parts = []
    current_part = ''
    
    # Split by bullet points or numbered items
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
    
    # Group items into parts that fit within max_chars
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

def process_audio_job_v2(meeting_id, media_url):
    """Enhanced worker function with dynamic messaging system"""
    print(f"🔧 WORKER V2: Starting process_audio_job_v2 for meeting_id={meeting_id}, media_url={media_url[:50] if media_url else 'None'}...")
    try:
        # Get meeting details
        print(f"🔧 WORKER V2: Fetching meeting details from DB for meeting_id={meeting_id}")
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT phone, audio_file, message_sid FROM meeting_notes WHERE id=%s", (meeting_id,))
            row = cur.fetchone()
            if not row:
                print(f"🔧 WORKER V2: ❌ Meeting {meeting_id} not found in DB")
                return {"error": "Meeting not found"}
            
            phone = row[0] if hasattr(row, '__getitem__') else row.phone
            audio_url = media_url or (row[1] if hasattr(row, '__getitem__') else row.audio_file)
            message_sid = row[2] if hasattr(row, '__getitem__') else row.message_sid
            print(f"🔧 WORKER V2: ✅ Found meeting for phone={phone}, message_sid={message_sid}")
        
        # Download audio
        print(f"🔧 WORKER V2: Downloading audio from {audio_url[:50]}...")
        auth = None
        twilio_sid = os.getenv("TWILIO_ACCOUNT_SID")
        twilio_token = os.getenv("TWILIO_AUTH_TOKEN")
        if "twilio.com" in audio_url and twilio_sid and twilio_token:
            auth = (twilio_sid, twilio_token)
        
        resp = requests.get(audio_url, auth=auth, timeout=60)
        resp.raise_for_status()
        print(f"🔧 WORKER V2: Downloaded {len(resp.content)} bytes")
        
        # Check file size (OpenAI limit is 25MB)
        file_size_mb = len(resp.content) / (1024 * 1024)
        print(f"🔧 WORKER V2: File size: {file_size_mb:.2f}MB")
        
        if file_size_mb > 24:
            raise ValueError(f"Audio file too large: {file_size_mb:.2f}MB (max 25MB)")
        
        # Determine file extension from content type
        content_type = resp.headers.get('Content-Type', '')
        if 'opus' in content_type.lower():
            suffix = '.opus'
        elif 'ogg' in content_type.lower():
            suffix = '.ogg'
        elif 'mp3' in content_type.lower() or 'mpeg' in content_type.lower():
            suffix = '.mp3'
        elif 'm4a' in content_type.lower() or 'mp4' in content_type.lower():
            suffix = '.m4a'
        else:
            suffix = '.mp3' if file_size_mb > 5 else '.ogg'
        
        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(resp.content)
            tmp_path = tmp.name
        print(f"🔧 WORKER V2: Saved to temp file {tmp_path}")
        
        # Get user's language preference
        try:
            from db_multilang import get_user_language
            user_language = get_user_language(phone) or 'en'
            print(f"🔧 WORKER V2: User language preference: {user_language}")
        except ImportError:
            user_language = 'en'
            print(f"🔧 WORKER V2: Multilang not available, using English")
        
        # Transcribe with multilang support
        print(f"🔧 WORKER V2: Starting transcription...")
        try:
            if user_language != 'en':
                from openai_client_multilang import transcribe_file_multilang
                transcript = transcribe_file_multilang(tmp_path, user_language)
            else:
                transcript = transcribe_file(tmp_path)
        except ImportError:
            transcript = transcribe_file(tmp_path)
        print(f"🔧 WORKER V2: Transcription complete, length: {len(transcript) if transcript else 0}")
        
        # Summarize with multilang support
        print(f"🔧 WORKER V2: Starting summarization...")
        try:
            if user_language != 'en':
                from openai_client_multilang import summarize_text_multilang
                summary = summarize_text_multilang(transcript, user_language)
            else:
                summary = summarize_text(transcript, "Create comprehensive meeting minutes with clear sections")
        except ImportError:
            summary = summarize_text(transcript, "Create comprehensive meeting minutes with clear sections")
        print(f"🔧 WORKER V2: Summarization complete, length: {len(summary) if summary else 0}")
        
        # Calculate duration
        try:
            from mutagen import File as MutagenFile
            mf = MutagenFile(tmp_path)
            if mf and hasattr(mf, 'info') and hasattr(mf.info, 'length'):
                duration_seconds = float(mf.info.length)
            else:
                duration_seconds = (len(resp.content) * 8) / 80000
            
            MAX_DURATION_SECONDS = 30 * 60
            if duration_seconds > MAX_DURATION_SECONDS:
                duration_seconds = MAX_DURATION_SECONDS
            
            minutes = round(duration_seconds / 60.0, 2)
            print(f"🔧 WORKER V2: Final duration: {minutes} minutes")
        except Exception:
            minutes = 1.0
        
        # Update database and deduct credits
        with get_conn() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT credits_remaining, subscription_active, subscription_expiry FROM users WHERE phone=%s FOR UPDATE",
                        (phone,)
                    )
                    user_row = cur.fetchone()
                    
                    if user_row:
                        credits = float(user_row[0] or 0.0)
                        sub_active = bool(user_row[1])
                        sub_expiry = user_row[2]
                        
                        from datetime import datetime, timezone
                        now = datetime.now(timezone.utc)
                        has_active_sub = sub_active and (sub_expiry is None or sub_expiry > now)
                        
                        if not has_active_sub and minutes > 0:
                            new_credits = max(0.0, credits - minutes)
                            cur.execute(
                                "UPDATE users SET credits_remaining=%s WHERE phone=%s",
                                (new_credits, phone)
                            )
                            print(f"🔧 WORKER V2: Deducted {minutes} minutes. Credits: {credits} -> {new_credits}")
                    
                    cur.execute(
                        "UPDATE meeting_notes SET transcript=%s, summary=%s WHERE id=%s",
                        (transcript, summary, meeting_id)
                    )
                    conn.commit()
                    print(f"🔧 WORKER V2: Database updates committed successfully")
                    
            except Exception as db_error:
                conn.rollback()
                print(f"🔧 WORKER V2: Database update failed: {db_error}")
                raise
        
        # Send result
        print(f"🔧 WORKER V2: Sending WhatsApp message to {phone}")
        send_whatsapp(phone, summary or "📝 Transcription completed.")
        
        # Cleanup
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
            
        return {"success": True, "meeting_id": meeting_id}
        
    except Exception as e:
        print(f"🔧 WORKER V2: Error in process_audio_job_v2 for meeting_id={meeting_id}: {e}")
        traceback.print_exc()
        try:
            if 'phone' in locals():
                send_whatsapp(phone, "⚠️ Processing failed. Please try again.")
        except Exception:
            pass
        return {"error": str(e)}

def test_worker_job():
    """Simple test function"""
    print("🧪 TEST WORKER JOB EXECUTED SUCCESSFULLY!")
    return "test_success"
