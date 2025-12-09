"""
Smart Follow-Ups & Task Completion Score
The killer feature for Indian market - automatic follow-ups with gamification
"""

import os
from datetime import datetime, timedelta
import pytz
from db import get_conn, get_user_by_phone
from utils import send_whatsapp
from psycopg2.extras import RealDictCursor

def get_user_completion_score(phone, days=7):
    """Calculate user's task completion score for last N days"""
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        user = get_user_by_phone(phone)
        if not user:
            return None
        
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        start_date = now - timedelta(days=days)
        
        # Get task stats
        cur.execute("""
            SELECT 
                COUNT(*) FILTER (WHERE status='done') as completed,
                COUNT(*) FILTER (WHERE status='open') as pending,
                COUNT(*) FILTER (WHERE status='open' AND due_at < now()) as overdue,
                COUNT(*) as total
            FROM tasks
            WHERE user_id = %s 
            AND created_at >= %s
            AND deleted = false
        """, (user['id'], start_date))
        
        stats = cur.fetchone()
        
        if not stats or stats['total'] == 0:
            return {
                'score': 0,
                'completed': 0,
                'pending': 0,
                'overdue': 0,
                'total': 0,
                'completion_rate': 0
            }
        
        completion_rate = int((stats['completed'] / stats['total']) * 100)
        
        # Score calculation: completion_rate - (overdue_penalty * 5)
        overdue_penalty = min(stats['overdue'], 10)  # Cap at 10
        score = max(0, completion_rate - (overdue_penalty * 5))
        
        return {
            'score': score,
            'completed': stats['completed'],
            'pending': stats['pending'],
            'overdue': stats['overdue'],
            'total': stats['total'],
            'completion_rate': completion_rate
        }

def send_personal_followup(phone, task):
    """Send personalized follow-up for a specific task"""
    title = task.get('title', 'Your task')
    due_at = task.get('due_at')
    task_id = task.get('id')
    
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    
    # Determine message tone based on deadline
    if due_at:
        due_date = due_at if isinstance(due_at, datetime) else datetime.fromisoformat(str(due_at))
        if due_date.tzinfo is None:
            due_date = ist.localize(due_date)
        
        days_until = (due_date - now).days
        
        if days_until < 0:
            # Overdue
            message = f"⚠️ *Overdue Reminder*\n\n📌 {title}\n\n🗓️ Was due: {due_date.strftime('%b %d')}\n\nReply 'Done {task_id}' when complete.\n\n_Sent via MinA - Your AI Assistant_"
        elif days_until == 0:
            # Due today
            message = f"🔔 *Due Today!*\n\n📌 {title}\n\n⏰ Deadline: Today\n\nReply 'Done {task_id}' when complete.\n\n_Sent via MinA - Your AI Assistant_"
        elif days_until == 1:
            # Due tomorrow
            message = f"📅 *Reminder*\n\n📌 {title}\n\n⏰ Due: Tomorrow\n\nReply 'Done {task_id}' when complete.\n\n_Sent via MinA - Your AI Assistant_"
        else:
            # Future deadline
            message = f"📝 *Upcoming Task*\n\n📌 {title}\n\n⏰ Due: {due_date.strftime('%b %d')} ({days_until} days)\n\nReply 'Done {task_id}' when complete.\n\n_Sent via MinA - Your AI Assistant_"
    else:
        # No deadline
        message = f"📝 *Task Reminder*\n\n📌 {title}\n\nReply 'Done {task_id}' when complete.\n\n_Sent via MinA - Your AI Assistant_"
    
    send_whatsapp(phone, message)
    return True

def send_daily_followup():
    """Send daily follow-ups to users with pending tasks"""
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        
        # Get users with tasks due today or overdue
        cur.execute("""
            SELECT DISTINCT u.phone, u.id as user_id
            FROM users u
            JOIN tasks t ON t.user_id = u.id
            WHERE t.status = 'open'
            AND t.deleted = false
            AND (
                DATE(t.due_at) = DATE(now())
                OR t.due_at < now()
            )
        """)
        
        users = cur.fetchall()
        sent_count = 0
        
        for user in users:
            phone = user['phone']
            user_id = user['user_id']
            
            # Get their urgent tasks
            cur.execute("""
                SELECT id, title, due_at
                FROM tasks
                WHERE user_id = %s
                AND status = 'open'
                AND deleted = false
                AND (
                    DATE(due_at) = DATE(now())
                    OR due_at < now()
                )
                ORDER BY due_at ASC
                LIMIT 3
            """, (user_id,))
            
            tasks = cur.fetchall()
            
            if tasks:
                # Send follow-up for first urgent task
                send_personal_followup(phone, dict(tasks[0]))
                sent_count += 1
        
        return sent_count

def send_weekly_scorecard():
    """Send weekly completion scorecard to all active users"""
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Get all users who had tasks in last 7 days
        cur.execute("""
            SELECT DISTINCT u.phone
            FROM users u
            JOIN tasks t ON t.user_id = u.id
            WHERE t.created_at >= now() - interval '7 days'
        """)
        
        users = cur.fetchall()
        sent_count = 0
        
        for user in users:
            phone = user['phone']
            score_data = get_user_completion_score(phone, days=7)
            
            if not score_data or score_data['total'] == 0:
                continue
            
            # Generate scorecard message
            score = score_data['score']
            completed = score_data['completed']
            pending = score_data['pending']
            overdue = score_data['overdue']
            completion_rate = score_data['completion_rate']
            
            # Determine emoji and message based on score
            if score >= 90:
                emoji = "🏆"
                message_tone = "Outstanding performance!"
            elif score >= 75:
                emoji = "⭐"
                message_tone = "Great work!"
            elif score >= 60:
                emoji = "👍"
                message_tone = "Good progress!"
            elif score >= 40:
                emoji = "📈"
                message_tone = "Keep pushing!"
            else:
                emoji = "💪"
                message_tone = "Let's improve this week!"
            
            message = f"""{emoji} *Weekly Task Score*

{message_tone}

📊 *Your Score: {score}/100*

✅ Completed: {completed}
⏳ Pending: {pending}
⚠️ Overdue: {overdue}
📈 Completion Rate: {completion_rate}%

{'🎯 Amazing! Keep it up!' if score >= 75 else '💡 Tip: Complete overdue tasks first to boost your score!'}

_Sent via MinA - Your AI Assistant_"""
            
            send_whatsapp(phone, message)
            sent_count += 1
        
        return sent_count

def send_gentle_nudge():
    """Send gentle nudge to users with tasks pending for 2+ days"""
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        ist = pytz.timezone('Asia/Kolkata')
        two_days_ago = datetime.now(ist) - timedelta(days=2)
        
        # Get users with old pending tasks
        cur.execute("""
            SELECT DISTINCT u.phone, u.id as user_id
            FROM users u
            JOIN tasks t ON t.user_id = u.id
            WHERE t.status = 'open'
            AND t.deleted = false
            AND t.created_at < %s
            AND t.due_at IS NULL
        """, (two_days_ago,))
        
        users = cur.fetchall()
        sent_count = 0
        
        for user in users:
            phone = user['phone']
            user_id = user['user_id']
            
            # Count their old tasks
            cur.execute("""
                SELECT COUNT(*) as count
                FROM tasks
                WHERE user_id = %s
                AND status = 'open'
                AND deleted = false
                AND created_at < %s
            """, (user_id, two_days_ago))
            
            result = cur.fetchone()
            count = result['count'] if result else 0
            
            if count > 0:
                message = f"""💭 *Gentle Reminder*

You have {count} task{'s' if count > 1 else ''} pending for 2+ days.

Need help prioritizing? Reply 'Show my tasks' to see your list.

_Sent via MinA - Your AI Assistant_"""
                
                send_whatsapp(phone, message)
                sent_count += 1
        
        return sent_count

def get_team_leaderboard(phone_list, days=7):
    """Get leaderboard for a team (future feature for groups)"""
    leaderboard = []
    
    for phone in phone_list:
        score_data = get_user_completion_score(phone, days)
        if score_data and score_data['total'] > 0:
            leaderboard.append({
                'phone': phone,
                'score': score_data['score'],
                'completed': score_data['completed'],
                'completion_rate': score_data['completion_rate']
            })
    
    # Sort by score descending
    leaderboard.sort(key=lambda x: x['score'], reverse=True)
    return leaderboard
