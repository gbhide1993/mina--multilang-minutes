#!/usr/bin/env python3
"""
Advanced Features for MinA - Daily Habit Formation
- Task completion check-in (11 AM)
- Weekly progress summary (Sunday 8 PM)
- Group tasks by project/client
- Interactive task completion
"""

import json
from datetime import datetime, timedelta
from db import get_conn, mark_task_done
from utils import send_whatsapp

def get_tasks_grouped_by_project(phone):
    """Get tasks grouped by project/client"""
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT t.id, t.title, t.due_at, t.metadata 
                FROM tasks t
                JOIN users u ON t.user_id = u.id
                WHERE u.phone=%s AND t.status='open' AND t.deleted=false
                ORDER BY t.due_at
            """, (phone,))
            tasks = cur.fetchall()
        
        grouped = {}
        for task in tasks:
            metadata = json.loads(task[3]) if task[3] else {}
            project = metadata.get('project', 'General')
            if project not in grouped:
                grouped[project] = []
            grouped[project].append({
                'id': task[0],
                'title': task[1],
                'due_at': task[2]
            })
        
        return grouped
    except Exception as e:
        print(f"Error grouping tasks: {e}")
        return {}

def send_task_completion_prompt(phone):
    """Ask user about specific overdue/due-today tasks"""
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT t.id, t.title FROM tasks t
                JOIN users u ON t.user_id = u.id
                WHERE u.phone=%s AND t.status='open' 
                AND (t.due_at < NOW() OR DATE(t.due_at) = CURRENT_DATE)
                AND t.deleted=false
                ORDER BY t.due_at LIMIT 3
            """, (phone,))
            tasks = cur.fetchall()
        
        if not tasks:
            return False
        
        message = "⏰ *Task Check-In*\n\n"
        for task in tasks:
            task_id = task[0]
            title = task[1]
            message += f"📌 {title}\n   Reply 'Done {task_id}' to complete\n\n"
        
        message += "Did you complete any of these?"
        
        send_whatsapp(phone, message)
        print(f"✅ Task check-in sent to {phone}")
        return True
    except Exception as e:
        print(f"❌ Error sending completion prompt: {e}")
        return False

def get_weekly_stats(phone):
    """Get task statistics for the past week"""
    week_ago = datetime.utcnow() - timedelta(days=7)
    
    try:
        with get_conn() as conn, conn.cursor() as cur:
            # Completed this week
            cur.execute("""
                SELECT COUNT(*) FROM tasks t
                JOIN users u ON t.user_id = u.id
                WHERE u.phone=%s AND t.status='done' 
                AND t.updated_at >= %s
            """, (phone, week_ago))
            completed = cur.fetchone()[0]
            
            # Created this week
            cur.execute("""
                SELECT COUNT(*) FROM tasks t
                JOIN users u ON t.user_id = u.id
                WHERE u.phone=%s AND t.created_at >= %s
            """, (phone, week_ago))
            created = cur.fetchone()[0]
            
            # Still pending
            cur.execute("""
                SELECT COUNT(*) FROM tasks t
                JOIN users u ON t.user_id = u.id
                WHERE u.phone=%s AND t.status='open' AND t.deleted=false
            """, (phone,))
            pending = cur.fetchone()[0]
            
            completion_rate = (completed / created * 100) if created > 0 else 0
            
            return {
                'completed': completed,
                'created': created,
                'pending': pending,
                'completion_rate': completion_rate
            }
    except Exception as e:
        print(f"Error getting weekly stats: {e}")
        return {'completed': 0, 'created': 0, 'pending': 0, 'completion_rate': 0}

def send_weekly_summary(phone):
    """Send weekly progress summary"""
    try:
        stats = get_weekly_stats(phone)
        
        message = f"""📊 *Weekly Progress Summary*

This week you:
✅ Completed {stats['completed']} tasks
📝 Created {stats['created']} new tasks
⏳ Have {stats['pending']} tasks pending

Completion Rate: {stats['completion_rate']:.0f}%

"""
        
        # Motivational message
        if stats['completion_rate'] >= 80:
            message += "🎉 Amazing work! You're crushing it!"
        elif stats['completion_rate'] >= 50:
            message += "💪 Great progress! Keep it up!"
        else:
            message += "📈 Let's make next week even better!"
        
        message += "\n\nReady to plan next week?"
        
        send_whatsapp(phone, message)
        print(f"✅ Weekly summary sent to {phone}")
        return True
    except Exception as e:
        print(f"❌ Error sending weekly summary: {e}")
        return False

def send_grouped_morning_reminder(phone):
    """Send morning reminder with tasks grouped by project"""
    try:
        grouped = get_tasks_grouped_by_project(phone)
        
        if not grouped:
            message = "🌅 Good morning! You have no pending tasks today. Have a great day!"
        else:
            total = sum(len(tasks) for tasks in grouped.values())
            message = f"🌅 Good morning! You have {total} pending task{'s' if total != 1 else ''}:\n\n"
            
            for project, tasks in grouped.items():
                message += f"📁 *{project}*\n"
                for task in tasks[:3]:
                    message += f"  • {task['title']}\n"
                if len(tasks) > 3:
                    message += f"  ... and {len(tasks)-3} more\n"
                message += "\n"
            
            message += "Want to review them?"
        
        send_whatsapp(phone, message)
        print(f"✅ Grouped morning reminder sent to {phone}")
        return True
    except Exception as e:
        print(f"❌ Error sending grouped reminder: {e}")
        return False

def schedule_task_checkins():
    """Send task check-ins to all users (11 AM)"""
    from scheduled_reminders import get_all_active_users
    users = get_all_active_users()
    sent_count = 0
    
    for phone in users:
        if send_task_completion_prompt(phone):
            sent_count += 1
    
    print(f"📅 Task check-ins: {sent_count}/{len(users)} sent")
    return sent_count

def schedule_weekly_summaries():
    """Send weekly summaries to all users (Sunday 8 PM)"""
    from scheduled_reminders import get_all_active_users
    users = get_all_active_users()
    sent_count = 0
    
    for phone in users:
        if send_weekly_summary(phone):
            sent_count += 1
    
    print(f"📅 Weekly summaries: {sent_count}/{len(users)} sent")
    return sent_count

def parse_task_completion_response(body_text, phone):
    """Parse user response for task completion"""
    body_lower = body_text.lower().strip()
    
    # Match "Done 1", "Complete 2", "Finished 3", etc.
    keywords = ['done', 'complete', 'finished', 'completed']
    
    for keyword in keywords:
        if body_lower.startswith(keyword + ' '):
            try:
                task_id = int(body_lower.split()[1])
                result = mark_task_done(task_id, phone)
                if result:
                    return {'success': True, 'task_id': task_id, 'message': f"✅ Task {task_id} marked as complete!"}
                else:
                    return {'success': False, 'message': f"❌ Task {task_id} not found or already completed."}
            except (ValueError, IndexError):
                return {'success': False, 'message': "❌ Invalid format. Use 'Done 1' or 'Complete 2'"}
    
    return None  # Not a task completion response
