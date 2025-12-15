#!/usr/bin/env python3
"""
Custom Reminders Extraction from Voice Notes
Extracts specific times mentioned in audio and schedules custom reminders
"""

import re
from datetime import datetime, timedelta
from dateutil import parser
from db import get_conn, create_task
from utils import send_whatsapp
from openai_client_multilang import summarize_text_multilang

def extract_custom_reminders(transcript, phone, meeting_id=None):
    """
    Extract custom reminder times from transcript and schedule them
    Returns: list of created reminders
    """
    try:
        # Use AI to extract reminders with specific times
        instruction = """
        Extract reminders with specific times from this transcript. Return JSON array with:
        - "task": the task description
        - "time": time in format "HH:MM" (24-hour) or "HH:MM AM/PM"
        - "date": date if mentioned (YYYY-MM-DD) or null for today
        - "recurring": true/false if it's a recurring reminder
        
        Examples:
        "Remind me at 2 PM to call John" -> {"task": "Call John", "time": "14:00", "date": null, "recurring": false}
        "Set a reminder for 9:30 AM tomorrow to send the report" -> {"task": "Send the report", "time": "09:30", "date": "2024-01-15", "recurring": false}
        
        Return only valid JSON array, no other text.
        """
        
        ai_response = summarize_text_multilang(
            transcript, 
            language_code="en", 
            instructions=instruction,
            max_tokens=500,
            temperature=0.0
        )
        
        # Parse AI response
        import json
        try:
            # Extract JSON from response
            start = ai_response.find('[')
            end = ai_response.rfind(']') + 1
            if start != -1 and end != -1:
                json_text = ai_response[start:end]
                reminders = json.loads(json_text)
            else:
                reminders = json.loads(ai_response)
        except:
            print(f"Failed to parse AI response: {ai_response}")
            return []
        
        created_reminders = []
        
        for reminder in reminders:
            try:
                task_text = reminder.get('task', '').strip()
                time_str = reminder.get('time', '').strip()
                date_str = reminder.get('date')
                recurring = reminder.get('recurring', False)
                
                if not task_text or not time_str:
                    continue
                
                # Parse time
                remind_time = parse_time_string(time_str)
                if not remind_time:
                    continue
                
                # Parse date (default to today if not specified)
                if date_str:
                    try:
                        remind_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                    except:
                        remind_date = datetime.now().date()
                else:
                    remind_date = datetime.now().date()
                
                # Combine date and time
                remind_datetime = datetime.combine(remind_date, remind_time)
                
                # Skip if time is in the past
                if remind_datetime <= datetime.now():
                    # If it's today and time passed, schedule for tomorrow
                    if remind_date == datetime.now().date():
                        remind_datetime += timedelta(days=1)
                    else:
                        continue
                
                # Create task with custom reminder time
                task = create_task(
                    phone=phone,
                    title=task_text,
                    due_at=remind_datetime.isoformat(),
                    priority=2,
                    source='voice_reminder',
                    metadata={
                        'meeting_id': meeting_id,
                        'custom_reminder': True,
                        'remind_at': remind_datetime.isoformat(),
                        'recurring': recurring
                    }
                )
                
                if task:
                    created_reminders.append({
                        'task_id': task.get('id'),
                        'task': task_text,
                        'remind_at': remind_datetime.isoformat(),
                        'recurring': recurring
                    })
                    
                    print(f"✅ Custom reminder created: '{task_text}' at {remind_datetime}")
                
            except Exception as e:
                print(f"Error creating reminder: {e}")
                continue
        
        return created_reminders
        
    except Exception as e:
        print(f"Error extracting custom reminders: {e}")
        return []

def parse_time_string(time_str):
    """
    Parse time string to time object
    Supports: "14:00", "2:00 PM", "2 PM", "14:30", etc.
    """
    try:
        time_str = time_str.strip().upper()
        
        # Handle "2 PM" format (no colon)
        if re.match(r'^\d{1,2}\s*(AM|PM)$', time_str):
            time_str = time_str.replace(' ', ':00 ')
        
        # Parse various time formats
        time_formats = [
            '%H:%M',      # 14:30
            '%I:%M %p',   # 2:30 PM
            '%I %p',      # 2 PM
            '%H',         # 14
        ]
        
        for fmt in time_formats:
            try:
                parsed = datetime.strptime(time_str, fmt).time()
                return parsed
            except ValueError:
                continue
        
        return None
        
    except Exception as e:
        print(f"Error parsing time '{time_str}': {e}")
        return None

def send_custom_reminder(task_id, phone, task_text):
    """
    Send custom reminder to user
    """
    try:
        message = f"⏰ *Custom Reminder*\n\n📌 {task_text}\n\nReply 'Done {task_id}' when completed."
        send_whatsapp(phone, message)
        
        # Mark reminder as sent
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE tasks 
                SET metadata = metadata || '{"reminder_sent": true}'::jsonb
                WHERE id = %s
            """, (task_id,))
            conn.commit()
        
        print(f"✅ Custom reminder sent to {phone}: {task_text}")
        return True
        
    except Exception as e:
        print(f"❌ Failed to send custom reminder: {e}")
        return False

def check_and_send_custom_reminders():
    """
    Check for custom reminders that need to be sent
    Called by scheduler every minute
    """
    try:
        with get_conn() as conn, conn.cursor() as cur:
            # Find tasks with custom reminders due now (within 1 minute)
            now = datetime.now()
            cur.execute("""
                SELECT t.id, t.title, u.phone, t.metadata
                FROM tasks t
                JOIN users u ON t.user_id = u.id
                WHERE t.status = 'open'
                AND t.metadata->>'custom_reminder' = 'true'
                AND t.metadata->>'reminder_sent' IS NULL
                AND t.due_at BETWEEN %s AND %s
            """, (now - timedelta(minutes=1), now + timedelta(minutes=1)))
            
            reminders = cur.fetchall()
            
            sent_count = 0
            for reminder in reminders:
                task_id = reminder[0] if hasattr(reminder, '__getitem__') else reminder.id
                title = reminder[1] if hasattr(reminder, '__getitem__') else reminder.title
                phone = reminder[2] if hasattr(reminder, '__getitem__') else reminder.phone
                
                if send_custom_reminder(task_id, phone, title):
                    sent_count += 1
            
            if sent_count > 0:
                print(f"📅 Sent {sent_count} custom reminders")
            
            return sent_count
            
    except Exception as e:
        print(f"Error checking custom reminders: {e}")
        return 0

def setup_custom_reminder_scheduler(scheduler):
    """
    Setup scheduler job for custom reminders (check every minute)
    """
    try:
        scheduler.add_job(
            func=check_and_send_custom_reminders,
            trigger='interval',
            minutes=1,
            id='custom_reminders_check',
            name='Custom Reminders Check (Every Minute)',
            replace_existing=True
        )
        print("✅ Custom reminders scheduler setup complete")
        return True
    except Exception as e:
        print(f"❌ Failed to setup custom reminder scheduler: {e}")
        return False
