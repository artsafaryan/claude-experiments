"""Scheduled jobs for email processing and follow-ups."""

from datetime import datetime
from typing import Optional, Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from ..email.processor import EmailProcessor
from ..email.gmail_client import GmailClient
from ..slack.bot import SlackBot
from ..database.repository import Repository, get_repository
from ..utils.config import get_app_config
from ..utils.logging import get_logger

logger = get_logger("scheduler")


class Scheduler:
    """Manages scheduled jobs for the automation system."""

    def __init__(
        self,
        email_processor: Optional[EmailProcessor] = None,
        slack_bot: Optional[SlackBot] = None,
        repository: Optional[Repository] = None,
    ):
        self.config = get_app_config()
        self.repo = repository or get_repository()

        # Initialize processor and bot if not provided
        self.email_processor = email_processor or EmailProcessor()
        self.slack_bot = slack_bot

        # Create scheduler
        self.scheduler = BackgroundScheduler()

        # Track if running
        self._is_running = False

    def setup_jobs(self):
        """Configure all scheduled jobs."""
        gmail_config = self.config.get("gmail", {})
        slack_config = self.config.get("slack", {})

        # Job 1: Check for new emails periodically
        check_interval = gmail_config.get("check_interval_seconds", 60)
        self.scheduler.add_job(
            self._check_emails_job,
            IntervalTrigger(seconds=check_interval),
            id="check_emails",
            name="Check for new emails",
            replace_existing=True,
        )
        logger.info(f"Scheduled email check every {check_interval} seconds")

        # Job 2: Send approval batches to Slack every 2 hours
        approval_interval = slack_config.get("approval_interval_hours", 2)
        self.scheduler.add_job(
            self._send_approvals_job,
            IntervalTrigger(hours=approval_interval),
            id="send_approvals",
            name="Send approval batch to Slack",
            replace_existing=True,
        )
        logger.info(f"Scheduled approval batch every {approval_interval} hours")

        # Job 3: Process follow-ups daily at 9 AM
        self.scheduler.add_job(
            self._process_follow_ups_job,
            CronTrigger(hour=9, minute=0),
            id="process_follow_ups",
            name="Process follow-up emails",
            replace_existing=True,
        )
        logger.info("Scheduled follow-up processing at 9 AM daily")

        # Job 4: Send daily summary at 9:30 AM
        self.scheduler.add_job(
            self._send_daily_summary_job,
            CronTrigger(hour=9, minute=30),
            id="daily_summary",
            name="Send daily summary",
            replace_existing=True,
        )
        logger.info("Scheduled daily summary at 9:30 AM")

    def _check_emails_job(self):
        """Job: Check for and process new emails."""
        logger.debug("Running email check job...")
        try:
            processed = self.email_processor.process_new_emails()
            if processed:
                logger.info(f"Processed {len(processed)} new emails")

                # Notify about high-priority items immediately
                high_priority = [
                    p for p in processed
                    if p.classification and p.classification.intent in ["accepting_offer", "submitting_content"]
                ]
                if high_priority and self.slack_bot:
                    for p in high_priority:
                        self.slack_bot.send_notification(
                            f"🚨 *High Priority*: {p.classification.intent.replace('_', ' ').title()} "
                            f"from conversation {p.conversation_id[:8]}..."
                        )

        except Exception as e:
            logger.error(f"Error in email check job: {e}")

    def _send_approvals_job(self):
        """Job: Send pending approvals to Slack."""
        logger.debug("Running approval batch job...")
        if self.slack_bot:
            try:
                self.slack_bot.send_approval_batch()
            except Exception as e:
                logger.error(f"Error in approval batch job: {e}")
        else:
            logger.warning("Slack bot not configured, skipping approval batch")

    def _process_follow_ups_job(self):
        """Job: Generate follow-up emails for stale conversations."""
        logger.debug("Running follow-up processing job...")
        try:
            processed = self.email_processor.process_follow_ups()
            if processed:
                logger.info(f"Generated {len(processed)} follow-up drafts")
        except Exception as e:
            logger.error(f"Error in follow-up job: {e}")

    def _send_daily_summary_job(self):
        """Job: Send daily summary to Slack."""
        logger.debug("Running daily summary job...")
        if not self.slack_bot:
            logger.warning("Slack bot not configured, skipping daily summary")
            return

        try:
            # Gather data for summary
            # This would normally query the database for recent activity
            new_responses = []  # TODO: Get from database
            pending_follow_ups = []  # TODO: Get conversations needing follow-up

            self.slack_bot.send_daily_summary(
                new_responses=new_responses,
                pending_follow_ups=pending_follow_ups,
            )
        except Exception as e:
            logger.error(f"Error in daily summary job: {e}")

    def start(self):
        """Start the scheduler."""
        if self._is_running:
            logger.warning("Scheduler already running")
            return

        self.setup_jobs()
        self.scheduler.start()
        self._is_running = True
        logger.info("Scheduler started")

    def stop(self):
        """Stop the scheduler."""
        if not self._is_running:
            return

        self.scheduler.shutdown(wait=True)
        self._is_running = False
        logger.info("Scheduler stopped")

    def run_now(self, job_id: str):
        """Manually trigger a job to run immediately."""
        job = self.scheduler.get_job(job_id)
        if job:
            logger.info(f"Manually running job: {job_id}")
            job.func()
        else:
            logger.warning(f"Job not found: {job_id}")

    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._is_running
