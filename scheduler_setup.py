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
        
        # Start scheduler
        if not scheduler.running:
            scheduler.start()
            logger.info("✅ APScheduler started with 5 jobs (9 AM, 12 PM, 3 PM, 6 PM, weekly)")
        
        # Shutdown scheduler on app exit
        atexit.register(lambda: scheduler.shutdown())
        
        return True
    except Exception as e:
        logger.error(f"❌ Failed to initialize scheduler: {e}")
        return False

def get_scheduler():
    """Get scheduler instance"""
    return scheduler
