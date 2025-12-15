#!/usr/bin/env python3
"""
APScheduler setup for MinA scheduled reminders
Integrates with Flask app to run scheduled jobs
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

def init_scheduler(app):
    """Initialize scheduler with Flask app"""
    try:
        from scheduled_reminders import schedule_morning_reminders, schedule_evening_summaries
        from advanced_features import schedule_task_checkins, schedule_weekly_summaries
        from smart_followups import send_daily_followup, send_weekly_scorecard, send_gentle_nudge
        
        # 9 AM IST (UTC+5:30) = 3:30 AM UTC
        scheduler.add_job(
            func=schedule_morning_reminders,
            trigger=CronTrigger(hour=3, minute=30),
            id='morning_reminder_9am_ist',
            name='Daily Morning Reminder (9 AM IST)',
            replace_existing=True
        )
        logger.info("✅ Morning reminder scheduled for 9 AM IST (3:30 AM UTC)")
        
        # 12 PM IST (UTC+5:30) = 6:30 AM UTC - Midday Check-In
        scheduler.add_job(
            func=schedule_task_checkins,
            trigger=CronTrigger(hour=6, minute=30),
            id='task_checkin_12pm_ist',
            name='Daily Midday Check-In (12 PM IST)',
            replace_existing=True
        )
        logger.info("✅ Midday check-in scheduled for 12 PM IST (6:30 AM UTC)")
        
        # 3 PM IST (UTC+5:30) = 9:30 AM UTC - Afternoon Check-In
        scheduler.add_job(
            func=schedule_task_checkins,
            trigger=CronTrigger(hour=9, minute=30),
            id='task_checkin_3pm_ist',
            name='Daily Afternoon Check-In (3 PM IST)',
            replace_existing=True
        )
        logger.info("✅ Afternoon check-in scheduled for 3 PM IST (9:30 AM UTC)")
        
        # 6 PM IST (UTC+5:30) = 12:30 PM UTC - Evening Summary
        scheduler.add_job(
            func=schedule_evening_summaries,
            trigger=CronTrigger(hour=12, minute=30),
            id='evening_summary_6pm_ist',
            name='Daily Evening Summary (6 PM IST)',
            replace_existing=True
        )
        logger.info("✅ Evening summary scheduled for 6 PM IST (12:30 PM UTC)")
        
        # Sunday 8 PM IST (UTC+5:30) = 2:30 PM UTC - Weekly Summary
        scheduler.add_job(
            func=schedule_weekly_summaries,
            trigger=CronTrigger(day_of_week='sun', hour=14, minute=30),
            id='weekly_summary_sunday_8pm_ist',
            name='Weekly Progress Summary (Sunday 8 PM IST)',
            replace_existing=True
        )
        logger.info("✅ Weekly summary scheduled for Sunday 8 PM IST (2:30 PM UTC)")
        
        # 10 AM IST (UTC+5:30) = 4:30 AM UTC - Daily Personal Follow-Up
        scheduler.add_job(
            func=send_daily_followup,
            trigger=CronTrigger(hour=4, minute=30),
            id='daily_followup_10am_ist',
            name='Daily Personal Follow-Up (10 AM IST)',
            replace_existing=True
        )
        logger.info("✅ Daily follow-up scheduled for 10 AM IST (4:30 AM UTC)")
        
        # Sunday 9 PM IST (UTC+5:30) = 3:30 PM UTC - Weekly Scorecard
        scheduler.add_job(
            func=send_weekly_scorecard,
            trigger=CronTrigger(day_of_week='sun', hour=15, minute=30),
            id='weekly_scorecard_sunday_9pm_ist',
            name='Weekly Task Completion Scorecard (Sunday 9 PM IST)',
            replace_existing=True
        )
        logger.info("✅ Weekly scorecard scheduled for Sunday 9 PM IST (3:30 PM UTC)")
        
        # Wednesday 4 PM IST (UTC+5:30) = 10:30 AM UTC - Gentle Nudge
        scheduler.add_job(
            func=send_gentle_nudge,
            trigger=CronTrigger(day_of_week='wed', hour=10, minute=30),
            id='gentle_nudge_wednesday_4pm_ist',
            name='Gentle Nudge for Old Tasks (Wednesday 4 PM IST)',
            replace_existing=True
        )
        logger.info("✅ Gentle nudge scheduled for Wednesday 4 PM IST (10:30 AM UTC)")
        
        # Custom reminders check (every minute)
        from custom_reminders import setup_custom_reminder_scheduler
        setup_custom_reminder_scheduler(scheduler)
        
        # Start scheduler
        if not scheduler.running:
            scheduler.start()
            logger.info("✅ APScheduler started with 9 jobs (morning, midday, afternoon, evening, weekly, follow-ups, scorecard, nudge, custom reminders)")
        
        # Shutdown scheduler on app exit
        atexit.register(lambda: scheduler.shutdown())
        
        return True
    except Exception as e:
        logger.error(f"❌ Failed to initialize scheduler: {e}")
        return False

def get_scheduler():
    """Get scheduler instance"""
    return scheduler
