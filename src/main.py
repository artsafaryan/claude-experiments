"""Main entry point for the Influencer Negotiation Automation System."""

import argparse
import sys
import time
from typing import Optional

from .database.repository import get_repository
from .database.models import init_db
from .email.gmail_client import GmailClient
from .email.processor import EmailProcessor
from .slack.bot import SlackBot
from .scheduler.jobs import Scheduler
from .utils.config import get_settings, get_app_config
from .utils.logging import setup_logging, get_logger


def setup_gmail_auth():
    """Interactive Gmail OAuth setup."""
    logger = get_logger("setup")
    logger.info("Starting Gmail OAuth setup...")

    client = GmailClient()
    if client.authenticate():
        email = client.get_user_email()
        logger.info(f"Successfully authenticated as: {email}")
        return True
    else:
        logger.error("Gmail authentication failed")
        return False


def run_email_check():
    """Run a single email check (useful for testing)."""
    logger = get_logger("main")
    logger.info("Running single email check...")

    processor = EmailProcessor()
    processed = processor.process_new_emails()

    logger.info(f"Processed {len(processed)} emails")
    for p in processed:
        logger.info(f"  - {p.action_taken}: {p.classification.summary if p.classification else 'N/A'}")

    return processed


def run_follow_up_check():
    """Check and generate follow-ups."""
    logger = get_logger("main")
    logger.info("Checking for follow-ups needed...")

    processor = EmailProcessor()
    follow_ups = processor.process_follow_ups()

    logger.info(f"Generated {len(follow_ups)} follow-up drafts")
    return follow_ups


def send_approvals():
    """Send pending approvals to Slack."""
    logger = get_logger("main")
    logger.info("Sending pending approvals to Slack...")

    bot = SlackBot()
    success = bot.send_approval_batch()

    if success:
        logger.info("Approval batch sent successfully")
    else:
        logger.error("Failed to send approval batch")

    return success


def run_daemon():
    """Run the full automation system as a daemon."""
    import threading

    logger = get_logger("main")
    logger.info("Starting Influencer Automation daemon...")

    settings = get_settings()
    config = get_app_config()

    # Initialize database
    init_db(settings.database_url)

    # Initialize components
    gmail_client = GmailClient()
    if not gmail_client.authenticate():
        logger.error("Gmail authentication failed. Run with --setup-gmail first.")
        sys.exit(1)

    processor = EmailProcessor(gmail_client=gmail_client)

    # Initialize Slack bot if configured
    slack_bot = None
    if settings.slack_bot_token and settings.slack_app_token:
        def on_approval(approval):
            """Callback when a response is approved."""
            # Get the response to send
            response_text = approval.edited_response or approval.draft_response
            conv = approval.conversation

            # Send the email
            gmail_client.send_email(
                to=conv.influencer.email,
                subject=f"Re: {conv.subject}",
                body=response_text,
                thread_id=conv.gmail_thread_id,
            )

            # Mark as sent
            repo = get_repository()
            repo.mark_approval_sent(approval.id)
            logger.info(f"Sent approved response for {conv.influencer.email}")

        slack_bot = SlackBot(
            on_approval_callback=on_approval,
            email_processor=processor,  # For manual "check emails" command
        )
        logger.info("Slack bot initialized")

        # Start Socket Mode in a separate thread so it doesn't block
        def start_slack_bot():
            try:
                slack_bot.start()
            except Exception as e:
                logger.error(f"Slack bot error: {e}")

        slack_thread = threading.Thread(target=start_slack_bot, daemon=True)
        slack_thread.start()
        logger.info("Slack Socket Mode started in background thread")
    else:
        logger.warning("Slack not fully configured - need SLACK_BOT_TOKEN and SLACK_APP_TOKEN")

    # Initialize scheduler
    scheduler = Scheduler(
        email_processor=processor,
        slack_bot=slack_bot,
    )

    # Start the scheduler
    scheduler.start()

    logger.info("Daemon running. Press Ctrl+C to stop.")

    try:
        # Keep the main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        scheduler.stop()


def show_status():
    """Show current system status."""
    logger = get_logger("main")
    repo = get_repository()

    from .database.models import InfluencerStatus

    print("\n=== Influencer Automation Status ===\n")

    # Count influencers by status
    statuses = [
        ("Sourced", InfluencerStatus.SOURCED),
        ("Contacted", InfluencerStatus.CONTACTED),
        ("Negotiating", InfluencerStatus.NEGOTIATING),
        ("Agreed", InfluencerStatus.AGREED),
        ("Declined", InfluencerStatus.DECLINED),
        ("Content Pending", InfluencerStatus.CONTENT_PENDING),
        ("Content Received", InfluencerStatus.CONTENT_RECEIVED),
        ("Completed", InfluencerStatus.COMPLETED),
    ]

    print("Influencers by Status:")
    for label, status in statuses:
        count = len(repo.get_influencers_by_status(status))
        if count > 0:
            print(f"  {label}: {count}")

    # Pending approvals
    pending = repo.get_pending_approvals()
    print(f"\nPending Approvals: {len(pending)}")

    # Conversations needing follow-up
    follow_ups = repo.get_conversations_needing_follow_up()
    print(f"Conversations Needing Follow-up: {len(follow_ups)}")

    print()


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Influencer Negotiation Automation System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.main --setup-gmail     # Set up Gmail OAuth
  python -m src.main --check-emails    # Process new emails once
  python -m src.main --send-approvals  # Send approvals to Slack
  python -m src.main --daemon          # Run as background service
  python -m src.main --status          # Show current status
        """,
    )

    parser.add_argument(
        "--setup-gmail",
        action="store_true",
        help="Run Gmail OAuth setup flow",
    )
    parser.add_argument(
        "--check-emails",
        action="store_true",
        help="Check for and process new emails (single run)",
    )
    parser.add_argument(
        "--check-follow-ups",
        action="store_true",
        help="Check for conversations needing follow-up",
    )
    parser.add_argument(
        "--send-approvals",
        action="store_true",
        help="Send pending approvals to Slack",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as a daemon (continuous background processing)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current system status",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Set logging level",
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_level)
    logger = get_logger("main")

    # Initialize database
    settings = get_settings()
    init_db(settings.database_url)

    # Execute requested action
    if args.setup_gmail:
        success = setup_gmail_auth()
        sys.exit(0 if success else 1)

    elif args.check_emails:
        run_email_check()

    elif args.check_follow_ups:
        run_follow_up_check()

    elif args.send_approvals:
        send_approvals()

    elif args.daemon:
        run_daemon()

    elif args.status:
        show_status()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
