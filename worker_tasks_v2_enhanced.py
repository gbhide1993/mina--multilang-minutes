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
                # Debug: Check if any meeting_notes exist
                cur.execute("SELECT COUNT(*) FROM meeting_notes")
                count = cur.fetchone()
                print(f"🔧 WORKER V2: Total meeting_notes in DB: {count[0] if count else 'unknown'}")
                return {"error": "Meeting not found"}
            
            phone = row[0] if hasattr(row, '__getitem__') else row.phone
            audio_url = media_url or (row[1] if hasattr(row, '__getitem__') else row.audio_file)
            message_sid = row[2] if hasattr(row, '__getitem__') else row.message_sid
            print(f"🔧 WORKER V2: ✅ Found meeting for phone={phone}, message_sid={message_sid}, audio_url={audio_url[:50] if audio_url else 'None'}...")
        
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
            raise ValueError(f"Audio file too large: {file_size_mb:.2f}MB (max 25MB). Please send a shorter recording.")
        
        # Determine file extension from content type
        content_type = resp.headers.get('Content-Type', '')
        print(f"🔧 WORKER V2: Content-Type: {content_type}")
        
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
        print(f"🔧 WORKER V2: Saved to temp file {tmp_path} (Content-Type: {content_type})")
        
        # Get user's language preference
        try:
            from db_multilang import get_user_language
            user_language = get_user_language(phone) or 'en'
            print(f"🔧 WORKER V2: User language preference: {user_language}")
        except ImportError:
            user_language = 'en'
            print(f"🔧 WORKER V2: Multilang not available, using English")
        
        # Transcribe with retry logic
        print(f"🔧 WORKER V2: Starting transcription of {tmp_path}...")
        try:
            # Use multilang transcription if available
            try:
                if user_language != 'en':
                    from openai_client_multilang import transcribe_file_multilang
                    transcript = transcribe_file_multilang(tmp_path, user_language)
                else:
                    transcript = transcribe_file(tmp_path)
            except ImportError:
                transcript = transcribe_file(tmp_path)
            print(f"🔧 WORKER V2: Transcription complete, length: {len(transcript) if transcript else 0}")
        except Exception as transcribe_error:
            print(f"🔧 WORKER V2: Transcription failed: {transcribe_error}")
            
            # For large files or 500 errors, try compressing with ffmpeg
            if file_size_mb > 10 or "500" in str(transcribe_error):
                print(f"🔧 WORKER V2: Attempting compression for large file...")
                try:
                    import subprocess
                    compressed_path = tmp_path.replace(suffix, '_compressed.mp3')
                    subprocess.run([
                        'ffmpeg', '-i', tmp_path, 
                        '-acodec', 'mp3', '-ab', '64k', 
                        '-ar', '16000', '-ac', '1',
                        compressed_path, '-y'
                    ], check=True, capture_output=True)
                    
                    compressed_size = os.path.getsize(compressed_path) / (1024 * 1024)
                    print(f"🔧 WORKER V2: Compressed to {compressed_size:.2f}MB, retrying transcription...")
                    
                    transcript = transcribe_file(compressed_path)
                    print(f"🔧 WORKER V2: Transcription successful after compression, length: {len(transcript)}")
                    
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                    tmp_path = compressed_path
                    
                except Exception as compress_error:
                    print(f"🔧 WORKER V2: Compression failed: {compress_error}")
                    raise transcribe_error
            else:
                try:
                    if tmp_path and os.path.exists(tmp_path):
                        file_size = os.path.getsize(tmp_path)
                        print(f"🔧 WORKER V2: File info - Size: {file_size} bytes, Path: {tmp_path}")
                except Exception as file_info_error:
                    print(f"🔧 WORKER V2: Could not get file info: {file_info_error}")
                raise
        
        # Summarize with enhanced prompt for better structure
        print(f"🔧 WORKER V2: Starting summarization...")
        # Use multilang summarization if available
        try:
            if user_language != 'en':
                from openai_client_multilang import summarize_text_multilang
                summary = summarize_text_multilang(transcript, user_language)
            else:
                summary = summarize_text(transcript, "Create comprehensive meeting minutes with clear sections: 1) Key Discussion Points 2) Important Decisions 3) Action Items with owners 4) Next Steps. Be specific and detailed. Use bullet points and clear formatting.")
        except ImportError:
            summary = summarize_text(transcript, "Create comprehensive meeting minutes with clear sections: 1) Key Discussion Points 2) Important Decisions 3) Action Items with owners 4) Next Steps. Be specific and detailed. Use bullet points and clear formatting.")
        print(f"🔧 WORKER V2: Summarization complete, length: {len(summary) if summary else 0}")
        
        # Calculate duration
        try:
            from mutagen import File as MutagenFile
            mf = MutagenFile(tmp_path)
            
            if mf and hasattr(mf, 'info') and hasattr(mf.info, 'length'):
                duration_seconds = float(mf.info.length)
                print(f"🔧 WORKER V2: Mutagen detected duration: {duration_seconds:.2f}s")
            else:
                duration_seconds = (len(resp.content) * 8) / 80000  # Conservative estimate
                print(f"🔧 WORKER V2: Using file size estimation: {duration_seconds:.2f}s")
            
            # Cap maximum duration (30 minutes max)
            MAX_DURATION_SECONDS = 30 * 60
            if duration_seconds > MAX_DURATION_SECONDS:
                print(f"🔧 WORKER V2: ⚠️ Duration capped from {duration_seconds:.2f}s to {MAX_DURATION_SECONDS}s")
                duration_seconds = MAX_DURATION_SECONDS
            
            minutes = round(duration_seconds / 60.0, 2)
            print(f"🔧 WORKER V2: Final duration: {duration_seconds:.2f}s ({minutes} minutes)")
            
        except Exception as duration_error:
            duration_seconds = min(len(resp.content) / 16000, 30 * 60)
            minutes = round(duration_seconds / 60.0, 2)
            print(f"🔧 WORKER V2: Duration calculation failed, using estimate: {minutes} minutes ({duration_error})")
        
        # Update database and deduct credits atomically
        with get_conn() as conn:
            try:
                with conn.cursor() as cur:
                    # Lock user row first
                    cur.execute(
                        "SELECT credits_remaining, subscription_active, subscription_expiry FROM users WHERE phone=%s FOR UPDATE",
                        (phone,)
                    )
                    user_row = cur.fetchone()
                    
                    credits_deducted = 0.0
                    if user_row:
                        credits = float(user_row[0] or 0.0)
                        sub_active = bool(user_row[1])
                        sub_expiry = user_row[2]
                        
                        print(f"🔧 WORKER V2: User status - Credits: {credits}, Sub active: {sub_active}, Sub expiry: {sub_expiry}")
                        
                        # Check subscription status
                        from datetime import datetime, timezone
                        now = datetime.now(timezone.utc)
                        has_active_sub = sub_active and (sub_expiry is None or sub_expiry > now)
                        
                        if not has_active_sub:
                            if minutes > 0:
                                new_credits = max(0.0, credits - minutes)
                                cur.execute(
                                    "UPDATE users SET credits_remaining=%s WHERE phone=%s",
                                    (new_credits, phone)
                                )
                                credits_deducted = minutes
                                print(f"🔧 WORKER V2: Deducted {minutes} minutes. Credits: {credits} -> {new_credits}")
                            else:
                                print(f"🔧 WORKER V2: No credits deducted - duration is 0 minutes")
                        else:
                            print(f"🔧 WORKER V2: Active subscription - no credits deducted")
                    else:
                        print(f"🔧 WORKER V2: No user row found for phone {phone} - creating default user")
                        cur.execute(
                            "INSERT INTO users (phone, credits_remaining, subscription_active) VALUES (%s, %s, %s) RETURNING credits_remaining",
                            (phone, 30.0, False)
                        )
                        new_user = cur.fetchone()
                        if new_user and minutes > 0:
                            new_credits = max(0.0, 30.0 - minutes)
                            cur.execute(
                                "UPDATE users SET credits_remaining=%s WHERE phone=%s",
                                (new_credits, phone)
                            )
                            credits_deducted = minutes
                            print(f"🔧 WORKER V2: Created new user and deducted {minutes} minutes. Credits: 30.0 -> {new_credits}")
                    
                    # Update meeting_notes
                    cur.execute(
                        "UPDATE meeting_notes SET transcript=%s, summary=%s WHERE id=%s",
                        (transcript, summary, meeting_id)
                    )
                    affected_rows = cur.rowcount
                    print(f"🔧 WORKER V2: Updated meeting_notes for meeting_id={meeting_id}, affected_rows={affected_rows}")
                    
                    # Commit both updates together
                    conn.commit()
                    print(f"🔧 WORKER V2: ✅ Database updates committed successfully (credits_deducted={credits_deducted})")
                    
            except Exception as db_error:
                conn.rollback()
                print(f"🔧 WORKER V2: ❌ Database update failed, rolled back: {db_error}")
                traceback.print_exc()
                raise
        
        # Send result
        print(f"🔧 WORKER V2: Sending WhatsApp message to {phone}")
        try:
            send_whatsapp(phone, summary or "📝 Transcription completed.")
            print(f"🔧 WORKER V2: WhatsApp message sent successfully to {phone}")
        except Exception as send_error:
            print(f"🔧 WORKER V2: Failed to send WhatsApp message to {phone}: {send_error}")
            raise
        
        # Cleanup
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception as cleanup_error:
            print(f"🔧 WORKER V2: Failed to cleanup temp file {tmp_path}: {cleanup_error}")
            
        return {"success": True, "meeting_id": meeting_id}
        
    except Exception as e:
        print(f"🔧 WORKER V2: Error in process_audio_job_v2 for meeting_id={meeting_id}: {e}")
        traceback.print_exc()
        try:
            if 'phone' in locals():
                print(f"🔧 WORKER V2: Sending error message to {phone}")
                send_whatsapp(phone, "⚠️ Processing failed. Please try again.")
                print(f"🔧 WORKER V2: Error message sent to {phone}")
        except Exception as send_error:
            print(f"🔧 WORKER V2: Failed to send error message: {send_error}")
        return {"error": str(e)}

def test_worker_job():
    """Simple test function"""
    print("🧪 TEST WORKER JOB EXECUTED SUCCESSFULLY!")
    return "test_success"..")
        # Use multilang summarization if available
        try:
            if user_language != 'en':
                from openai_client_multilang import summarize_text_multilang
                summary = summarize_text_multilang(transcript, user_language)
            else:
                summary = summarize_text(transcript, "Create comprehensive meeting minutes with clear sections: 1) Key Discussion Points 2) Important Decisions 3) Action Items with owners 4) Next Steps. Be specific and detailed. Use bullet points and clear formatting.")
        except ImportError:
            summary = summarize_text(transcript, "Create comprehensive meeting minutes with clear sections: 1) Key Discussion Points 2) Important Decisions 3) Action Items with owners 4) Next Steps. Be specific and detailed. Use bullet points and clear formatting.")
        print(f"🔧 WORKER V2: Summarization complete, length: {len(summary) if summary else 0}")
        
        # Calculate duration
        try:
            from mutagen import File as MutagenFile
            mf = MutagenFile(tmp_path)
            
            if mf and hasattr(mf, 'info') and hasattr(mf.info, 'length'):
                duration_seconds = float(mf.info.length)
                print(f"🔧 WORKER V2: Mutagen detected duration: {duration_seconds:.2f}s")
            else:
                duration_seconds = (len(resp.content) * 8) / 80000  # Conservative estimate
                print(f"🔧 WORKER V2: Using file size estimation: {duration_seconds:.2f}s")
            
            # Cap maximum duration (30 minutes max)
            MAX_DURATION_SECONDS = 30 * 60
            if duration_seconds > MAX_DURATION_SECONDS:
                print(f"🔧 WORKER V2: ⚠️ Duration capped from {duration_seconds:.2f}s to {MAX_DURATION_SECONDS}s")
                duration_seconds = MAX_DURATION_SECONDS
            
            minutes = round(duration_seconds / 60.0, 2)
            print(f"🔧 WORKER V2: Final duration: {duration_seconds:.2f}s ({minutes} minutes)")
            
        except Exception as duration_error:
            duration_seconds = min(len(resp.content) / 16000, 30 * 60)
            minutes = round(duration_seconds / 60.0, 2)
            print(f"🔧 WORKER V2: Duration calculation failed, using estimate: {minutes} minutes ({duration_error})")
        
        # Update database and deduct credits atomically
        with get_conn() as conn:
            try:
                with conn.cursor() as cur:
                    # Lock user row first
                    cur.execute(
                        "SELECT credits_remaining, subscription_active, subscription_expiry FROM users WHERE phone=%s FOR UPDATE",
                        (phone,)
                    )
                    user_row = cur.fetchone()
                    
                    credits_deducted = 0.0
                    if user_row:
                        credits = float(user_row[0] or 0.0)
                        sub_active = bool(user_row[1])
                        sub_expiry = user_row[2]
                        
                        print(f"🔧 WORKER V2: User status - Credits: {credits}, Sub active: {sub_active}, Sub expiry: {sub_expiry}")
                        
                        # Check subscription status
                        from datetime import datetime, timezone
                        now = datetime.now(timezone.utc)
                        has_active_sub = sub_active and (sub_expiry is None or sub_expiry > now)
                        
                        if not has_active_sub:
                            if minutes > 0:
                                new_credits = max(0.0, credits - minutes)
                                cur.execute(
                                    "UPDATE users SET credits_remaining=%s WHERE phone=%s",
                                    (new_credits, phone)
                                )
                                credits_deducted = minutes
                                print(f"🔧 WORKER V2: Deducted {minutes} minutes. Credits: {credits} -> {new_credits}")
                            else:
                                print(f"🔧 WORKER V2: No credits deducted - duration is 0 minutes")
                        else:
                            print(f"🔧 WORKER V2: Active subscription - no credits deducted")
                    else:
                        print(f"🔧 WORKER V2: No user row found for phone {phone} - creating default user")
                        cur.execute(
                            "INSERT INTO users (phone, credits_remaining, subscription_active) VALUES (%s, %s, %s) RETURNING credits_remaining",
                            (phone, 30.0, False)
                        )
                        new_user = cur.fetchone()
                        if new_user and minutes > 0:
                            new_credits = max(0.0, 30.0 - minutes)
                            cur.execute(
                                "UPDATE users SET credits_remaining=%s WHERE phone=%s",
                                (new_credits, phone)
                            )
                            credits_deducted = minutes
                            print(f"🔧 WORKER V2: Created new user and deducted {minutes} minutes. Credits: 30.0 -> {new_credits}")
                    
                    # Update meeting_notes
                    cur.execute(
                        "UPDATE meeting_notes SET transcript=%s, summary=%s WHERE id=%s",
                        (transcript, summary, meeting_id)
                    )
                    affected_rows = cur.rowcount
                    print(f"🔧 WORKER V2: Updated meeting_notes for meeting_id={meeting_id}, affected_rows={affected_rows}")
                    
                    # Commit both updates together
                    conn.commit()
                    print(f"🔧 WORKER V2: ✅ Database updates committed successfully (credits_deducted={credits_deducted})")
                    
                    # Verify the update worked
                    cur.execute("SELECT transcript IS NOT NULL, summary IS NOT NULL FROM meeting_notes WHERE id=%s", (meeting_id,))
                    verify_row = cur.fetchone()
                    if verify_row:
                        print(f"🔧 WORKER V2: ✅ Verification - transcript_saved={verify_row[0]}, summary_saved={verify_row[1]}")
                    else:
                        print(f"🔧 WORKER V2: ⚠️ Verification failed - meeting_id {meeting_id} not found after update")
                    
            except Exception as db_error:
                conn.rollback()
                print(f"🔧 WORKER V2: ❌ Database update failed, rolled back: {db_error}")
                print(f"🔧 WORKER V2: ❌ Failed for meeting_id={meeting_id}, phone={phone}")
                traceback.print_exc()
                raise
        
        # Send enhanced two-message summary
        print(f"🔧 WORKER V2: Sending WhatsApp messages to {phone}")
        try:
            if summary:
                # Dynamic messaging based on content structure - prioritize action items
                max_chars = 1400
                import time
                
                # Extract different sections from summary
                sections = _parse_summary_sections(summary)
                
                # Always send discussion points first (ensure ≤1400 chars)
                if sections['discussion']:
                    disc_header = "📝 *Meeting Summary - Discussion*\n\n"
                    available_chars = max_chars - len(disc_header)
                    
                    if len(sections['discussion']) <= available_chars:
                        msg1 = disc_header + sections['discussion']
                    else:
                        msg1 = disc_header + sections['discussion'][:available_chars-15] + "\n\n...(continued)"
                    
                    send_whatsapp(phone, msg1)
                    print(f"🔧 WORKER V2: Discussion sent ({len(msg1)} chars) to {phone}")
                    time.sleep(2)
                
                # Always send action items (KEY USP) - never truncate, ensure ≤1400 chars each
                if sections['actions']:
                    action_header = "✅ *Action Items & Next Steps*\n\n"
                    available_chars = max_chars - len(action_header)
                    
                    if len(sections['actions']) <= available_chars:
                        # Single action message
                        action_msg = action_header + sections['actions']
                        send_whatsapp(phone, action_msg)
                        print(f"🔧 WORKER V2: Actions sent ({len(action_msg)} chars) to {phone}")
                    else:
                        # Split actions into multiple messages, each ≤1400 chars
                        action_parts = _split_actions_intelligently(sections['actions'], available_chars)
                        for i, part in enumerate(action_parts, 1):
                            part_header = f"✅ *Action Items - Part {i}*\n\n"
                            msg = part_header + part
                            # Double-check length
                            if len(msg) > max_chars:
                                part = part[:max_chars - len(part_header) - 10] + "..."
                                msg = part_header + part
                            
                            send_whatsapp(phone, msg)
                            print(f"🔧 WORKER V2: Actions Part {i} sent ({len(msg)} chars) to {phone}")
                            if i < len(action_parts):
                                time.sleep(2)
                    time.sleep(2)
                
                # Send decisions if present (ensure ≤1400 chars)
                if sections['decisions']:
                    dec_header = "📝 *Key Decisions*\n\n"
                    available_chars = max_chars - len(dec_header)
                    
                    if len(sections['decisions']) <= available_chars:
                        dec_msg = dec_header + sections['decisions']
                    else:
                        dec_msg = dec_header + sections['decisions'][:available_chars-25] + "\n\n...(see full transcript)"
                    
                    send_whatsapp(phone, dec_msg)
                    print(f"🔧 WORKER V2: Decisions sent ({len(dec_msg)} chars) to {phone}")
                
                # Fallback if no structured sections found (ensure ≤1400 chars each)
                if not any(sections.values()):
                    # Send as multiple chunks, each ≤1400 chars
                    chunk_header = "📝 *Meeting Summary - Part {}*\n\n"
                    base_header_len = len(chunk_header.format(1))
                    chunk_size = max_chars - base_header_len
                    
                    chunks = [summary[i:i+chunk_size] for i in range(0, len(summary), chunk_size)]
                    for i, chunk in enumerate(chunks, 1):
                        msg = chunk_header.format(i) + chunk
                        # Final safety check
                        if len(msg) > max_chars:
                            chunk = chunk[:max_chars - len(chunk_header.format(i))]
                            msg = chunk_header.format(i) + chunk
                        
                        send_whatsapp(phone, msg)
                        print(f"🔧 WORKER V2: Chunk {i} sent ({len(msg)} chars) to {phone}")
                        if i < len(chunks):
                            time.sleep(2)
            else:
                send_whatsapp(phone, "📝 Transcription completed.")
                print(f"🔧 WORKER V2: Completion message sent to {phone}")
        except Exception as send_error:
            print(f"🔧 WORKER V2: Failed to send WhatsApp message to {phone}: {send_error}")
            raise
        
        # Cleanup
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception as cleanup_error:
            print(f"🔧 WORKER V2: Failed to cleanup temp file {tmp_path}: {cleanup_error}")
            
        return {"success": True, "meeting_id": meeting_id}
        
    except Exception as e:
        print(f"🔧 WORKER V2: Error in process_audio_job_v2 for meeting_id={meeting_id}: {e}")
        traceback.print_exc()
        try:
            if 'phone' in locals():
                print(f"🔧 WORKER V2: Sending error message to {phone}")
                send_whatsapp(phone, "⚠️ Processing failed. Please try again.")
                print(f"🔧 WORKER V2: Error message sent to {phone}")
        except Exception as send_error:
            print(f"🔧 WORKER V2: Failed to send error message: {send_error}")
        return {"error": str(e)}

def test_worker_job():
    """Simple test function"""
    print("🧪 TEST WORKER JOB EXECUTED SUCCESSFULLY!")
    return "test_success"
