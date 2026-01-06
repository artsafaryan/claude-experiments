"""Slack bot for handling approvals and notifications."""

from typing import Optional, Callable
from datetime import datetime

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from .messages import MessageBuilder
from ..database.repository import Repository, get_repository
from ..database.models import ApprovalStatus
from ..utils.config import get_settings, get_app_config
from ..utils.logging import get_logger

logger = get_logger("slack")


class SlackBot:
    """Slack bot for approval workflow and notifications."""

    def __init__(
        self,
        repository: Optional[Repository] = None,
        on_approval_callback: Optional[Callable] = None,
    ):
        self.settings = get_settings()
        self.app_config = get_app_config()
        self.repo = repository or get_repository()
        self.on_approval_callback = on_approval_callback

        # Initialize Slack app
        self.app = App(
            token=self.settings.slack_bot_token,
            signing_secret=self.settings.slack_signing_secret,
        )
        self.client = self.app.client

        # Get channel from config
        slack_config = self.app_config.get("slack", {})
        self.channel = slack_config.get("summary_channel", "#influencer-updates")

        # Register handlers
        self._register_handlers()

    def _register_handlers(self):
        """Register Slack event and action handlers."""

        @self.app.action("approve_response")
        def handle_approve(ack, body, client):
            ack()
            approval_id = body["actions"][0]["value"]
            user = body["user"]["username"]
            self._handle_approval(approval_id, user, client, body)

        @self.app.action("reject_response")
        def handle_reject(ack, body, client):
            ack()
            approval_id = body["actions"][0]["value"]
            user = body["user"]["username"]
            self._handle_rejection(approval_id, user, client, body)

        @self.app.action("edit_response")
        def handle_edit(ack, body, client):
            ack()
            approval_id = body["actions"][0]["value"]
            self._open_edit_modal(approval_id, body["trigger_id"], client)

        @self.app.action("view_full")
        def handle_view_full(ack, body, client):
            ack()
            approval_id = body["actions"][0]["value"]
            self._show_full_details(approval_id, body["trigger_id"], client)

        @self.app.action("approve_all")
        def handle_approve_all(ack, body, client):
            ack()
            user = body["user"]["username"]
            self._handle_approve_all(user, client, body)

        @self.app.view_submission("")
        def handle_modal_submission(ack, body, client, view):
            ack()
            if view["callback_id"].startswith("edit_modal_"):
                approval_id = view["private_metadata"]
                edited_text = view["state"]["values"]["response_input"]["response_text"]["value"]
                user = body["user"]["username"]
                self._handle_edited_approval(approval_id, edited_text, user, client)

    def _handle_approval(self, approval_id: str, user: str, client: WebClient, body: dict):
        """Handle approval of a response."""
        try:
            approval = self.repo.approve_response(approval_id)
            if approval:
                logger.info(f"Response {approval_id} approved by {user}")

                # Trigger callback to send email
                if self.on_approval_callback:
                    self.on_approval_callback(approval)

                # Update message
                self._update_approval_message(
                    client,
                    body["channel"]["id"],
                    body["message"]["ts"],
                    f"✅ Approved by @{user}",
                )

        except Exception as e:
            logger.error(f"Error handling approval: {e}")

    def _handle_rejection(self, approval_id: str, user: str, client: WebClient, body: dict):
        """Handle rejection of a response."""
        try:
            self.repo.reject_response(approval_id)
            logger.info(f"Response {approval_id} rejected by {user}")

            self._update_approval_message(
                client,
                body["channel"]["id"],
                body["message"]["ts"],
                f"❌ Rejected by @{user}",
            )

        except Exception as e:
            logger.error(f"Error handling rejection: {e}")

    def _handle_edited_approval(
        self, approval_id: str, edited_text: str, user: str, client: WebClient
    ):
        """Handle approval with edited response."""
        try:
            approval = self.repo.approve_response(approval_id, edited_response=edited_text)
            if approval:
                logger.info(f"Response {approval_id} edited and approved by {user}")

                if self.on_approval_callback:
                    self.on_approval_callback(approval)

        except Exception as e:
            logger.error(f"Error handling edited approval: {e}")

    def _handle_approve_all(self, user: str, client: WebClient, body: dict):
        """Handle bulk approval of all pending responses."""
        try:
            pending = self.repo.get_pending_approvals()
            approved_count = 0

            for approval in pending:
                self.repo.approve_response(approval.id)
                if self.on_approval_callback:
                    self.on_approval_callback(approval)
                approved_count += 1

            logger.info(f"{approved_count} responses approved by {user}")

            # Send confirmation
            client.chat_postMessage(
                channel=body["channel"]["id"],
                text=f"✅ {approved_count} responses approved and sent by @{user}",
            )

        except Exception as e:
            logger.error(f"Error handling bulk approval: {e}")

    def _open_edit_modal(self, approval_id: str, trigger_id: str, client: WebClient):
        """Open modal for editing a response."""
        # Get approval details
        approvals = self.repo.get_pending_approvals()
        approval = next((a for a in approvals if a.id == approval_id), None)

        if not approval:
            return

        # Get influencer name from conversation
        conv = approval.conversation
        influencer = conv.influencer if conv else None
        influencer_name = influencer.name if influencer else "Unknown"

        modal = MessageBuilder.build_edit_modal(
            approval_id=approval_id,
            influencer_name=influencer_name,
            current_draft=approval.draft_response,
        )

        try:
            client.views_open(trigger_id=trigger_id, view=modal)
        except SlackApiError as e:
            logger.error(f"Error opening modal: {e}")

    def _show_full_details(self, approval_id: str, trigger_id: str, client: WebClient):
        """Show full details in a modal."""
        approvals = self.repo.get_pending_approvals()
        approval = next((a for a in approvals if a.id == approval_id), None)

        if not approval:
            return

        conv = approval.conversation
        influencer = conv.influencer if conv else None

        modal = {
            "type": "modal",
            "title": {"type": "plain_text", "text": "Full Details"},
            "close": {"type": "plain_text", "text": "Close"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Influencer:* {influencer.name if influencer else 'Unknown'}\n"
                        f"*Email:* {influencer.email if influencer else 'Unknown'}\n"
                        f"*Platform:* {influencer.platform if influencer else 'Unknown'}\n"
                        f"*Followers:* {influencer.follower_count if influencer else 'Unknown'}",
                    },
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Their Message:*\n{approval.their_last_message or 'N/A'}",
                    },
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Drafted Response:*\n{approval.draft_response}",
                    },
                },
            ],
        }

        try:
            client.views_open(trigger_id=trigger_id, view=modal)
        except SlackApiError as e:
            logger.error(f"Error opening details modal: {e}")

    def _update_approval_message(
        self, client: WebClient, channel: str, ts: str, status_text: str
    ):
        """Update an approval message with status."""
        try:
            client.chat_update(
                channel=channel,
                ts=ts,
                text=status_text,
                blocks=[
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": status_text},
                    }
                ],
            )
        except SlackApiError as e:
            logger.error(f"Error updating message: {e}")

    def send_approval_batch(self) -> bool:
        """Send pending approvals to Slack for review."""
        pending = self.repo.get_pending_approvals()

        if not pending:
            logger.info("No pending approvals to send")
            return True

        logger.info(f"Sending {len(pending)} approvals to Slack")

        # Build approval data
        approvals_data = []
        for approval in pending:
            conv = approval.conversation
            influencer = conv.influencer if conv else None

            approvals_data.append({
                "id": approval.id,
                "influencer_name": influencer.name if influencer else "Unknown",
                "influencer_handle": influencer.handle if influencer else None,
                "their_message": approval.their_last_message or "",
                "draft_response": approval.draft_response,
                "response_type": approval.response_type,
                "their_rate": approval.their_rate,
                "our_counter": approval.our_counter,
                "priority": approval.priority,
            })

        blocks = MessageBuilder.build_approval_batch(approvals_data)

        try:
            response = self.client.chat_postMessage(
                channel=self.channel,
                text=f"{len(pending)} responses ready for approval",
                blocks=blocks,
            )

            # Store message timestamp for updates
            for approval in pending:
                approval.slack_message_ts = response["ts"]
                approval.slack_channel_id = response["channel"]

            logger.info(f"Approval batch sent to {self.channel}")
            return True

        except SlackApiError as e:
            logger.error(f"Error sending approval batch: {e}")
            return False

    def send_daily_summary(
        self,
        new_responses: list[dict],
        pending_follow_ups: list[dict],
    ) -> bool:
        """Send daily summary to Slack."""
        pending_count = len(self.repo.get_pending_approvals())

        blocks = MessageBuilder.build_daily_summary(
            new_responses=new_responses,
            pending_follow_ups=pending_follow_ups,
            pending_approvals=pending_count,
        )

        try:
            self.client.chat_postMessage(
                channel=self.channel,
                text="Daily influencer summary",
                blocks=blocks,
            )
            logger.info("Daily summary sent")
            return True

        except SlackApiError as e:
            logger.error(f"Error sending daily summary: {e}")
            return False

    def send_notification(self, message: str) -> bool:
        """Send a simple notification message."""
        try:
            self.client.chat_postMessage(
                channel=self.channel,
                text=message,
            )
            return True
        except SlackApiError as e:
            logger.error(f"Error sending notification: {e}")
            return False

    def start(self):
        """Start the Slack bot in socket mode."""
        handler = SocketModeHandler(self.app, self.settings.slack_app_token)
        logger.info("Starting Slack bot...")
        handler.start()
