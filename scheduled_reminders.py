#!/usr/bin/env python3
"""
Scheduled Reminders for MinA
- 9 AM: Daily Morning Reminder ("Your Workday Brief")
- 6 PM: End-of-Day Summary
"""

import os
from datetime import datetime, timedelta
from db import get_conn
from utils import send_whatsapp

def get_pending_tasks_count(phone):
    """Get count of pending tasks for user"""
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM tasks t
                JOIN users u ON t.user_id = u.id
                WHERE u.phone=%s AND t.status='open' AND t.deleted=false
            """, (phone,))
            row = cur.fetchone()
            return row[0] if row else 0
    except Exception as e:
        print(f"Error getting pending tasks: {e}")
        return 0

def get_completed_tasks_today(phone):
    """Get count of tasks completed today"""
    try:
        with get_conn() as conn, conn.cursor() as cur:
            today = datetime.utcnow().date()
            cur.execute("""
                SELECT COUNT(*) FROM tasks t
                JOIN users u ON t.user_id = u.id
                WHERE u.phone=%s AND t.status='done' AND DATE(t.updated_at)=%s
            """, (phone, today))
            row = cur.fetchone()
            return row[0] if row else 0
    except Exception as e:
        print(f"Error getting completed tasks: {e}")
        return 0

def get_overdue_tasks(phone):
    """Get count of overdue tasks"""
    try:
        with get_conn() as conn, conn.cursor() as cur:
            now = datetime.utcnow()
            cur.execute("""
                SELECT COUNT(*) FROM tasks t
                JOIN users u ON t.user_id = u.id
                WHERE u.phone=%s AND t.status='open' AND t.due_at < %s AND t.deleted=false
            """, (phone, now))
            row = cur.fetchone()
            return row[0] if row else 0
    except Exception as e:
        print(f"Error getting overdue tasks: {e}")
        return 0

def get_all_active_users():
    """Get all users who have used the service"""
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT phone FROM users WHERE created_at IS NOT NULL")
            rows = cur.fetchall()
            return [row[0] if hasattr(row, '__getitem__') else row.phone for row in rows]
    except Exception as e:
        print(f"Error getting active users: {e}")
        return []

def send_morning_reminder(phone):
    """Send 9 AM morning reminder with pending tasks count"""
    try:
        pending_count = get_pending_tasks_count(phone)
        
        if pending_count == 0:
            message = "🌅 Good morning! You have no pending tasks today. Have a great day!"
        elif pending_count == 1:
            message = "🌅 Good morning! You have 1 pending action item today.\nWant to review it?"
        else:
            message = f"🌅 Good morning! You have {pending_count} pending action items today.\nWant to review them?"
        
        send_whatsapp(phone, message)
        print(f"✅ Morning reminder sent to {phone} ({pending_count} tasks)")
        return True
    except Exception as e:
        print(f"❌ Failed to send morning reminder to {phone}: {e}")
        return False

def send_evening_summary(phone):
    """Send 6 PM end-of-day summary"""
    try:
        completed = get_completed_tasks_today(phone)
        overdue = get_overdue_tasks(phone)
        pending = get_pending_tasks_count(phone)
        
        message = f"""📊 *Your Day Summary*

✅ Completed: {completed} tasks
⏳ Pending: {pending} tasks
⚠️ Overdue: {overdue} tasks

Want me to prepare tomorrow's plan?"""
        
        send_whatsapp(phone, message)
        print(f"✅ Evening summary sent to {phone}")
        return True
    except Exception as e:
        print(f"❌ Failed to send evening summary to {phone}: {e}")
        return False

def schedule_morning_reminders():
    """Enqueue morning reminders for all users (call at 9 AM)"""
    users = get_all_active_users()
    sent_count = 0
    
    for phone in users:
        if send_morning_reminder(phone):
            sent_count += 1
    
    print(f"📅 Morning reminders: {sent_count}/{len(users)} sent")
    return sent_count

def schedule_evening_summaries():
    """Enqueue evening summaries for all users (call at 6 PM)"""
    users = get_all_active_users()
    sent_count = 0
    
    for phone in users:
        if send_evening_summary(phone):
            sent_count += 1
    
    print(f"📅 Evening summaries: {sent_count}/{len(users)} sent")
    return sent_count

# For APScheduler integration
def setup_scheduled_jobs(scheduler):
    """Setup APScheduler jobs for reminders"""
    try:
        # 9 AM IST (UTC+5:30) = 3:30 AM UTC
        scheduler.add_job(
            schedule_morning_reminders,
            'cron',
            hour=3,
            minute=30,
            id='morning_reminder_9am_ist'
        )
        print("✅ Morning reminder scheduled for 9 AM IST")
        
        # 6 PM IST (UTC+5:30) = 12:30 PM UTC
        scheduler.add_job(
            schedule_evening_summaries,
            'cron',
            hour=12,
            minute=30,
            id='evening_summary_6pm_ist'
        )
        print("✅ Evening summary scheduled for 6 PM IST")
        
        return True
    except Exception as e:
        print(f"❌ Failed to setup scheduled jobs: {e}")
        return False
