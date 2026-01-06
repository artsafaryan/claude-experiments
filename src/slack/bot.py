"""Slack bot for handling approvals and notifications - conversational interface."""

import re
from typing import Optional, Callable
from datetime import datetime

import anthropic
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from .messages import MessageBuilder
from ..database.repository import Repository, get_repository
from ..database.models import ApprovalStatus, InfluencerStatus
from ..utils.config import get_settings, get_app_config
from ..utils.logging import get_logger

logger = get_logger("slack")


class SlackBot:
    """Conversational Slack bot for approval workflow and notifications."""

    def __init__(
        self,
        repository: Optional[Repository] = None,
        on_approval_callback: Optional[Callable] = None,
    ):
        self.settings = get_settings()
        self.app_config = get_app_config()
        self.repo = repository or get_repository()
        self.on_approval_callback = on_approval_callback

        # Initialize Claude client for conversational understanding
        self.claude = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)

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

        # ============== Button Actions ==============

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

        # ============== Modal Submissions ==============

        @self.app.view("edit_modal")
        def handle_edit_modal_submission(ack, body, client, view):
            ack()
            approval_id = view["private_metadata"]
            edited_text = view["state"]["values"]["response_input"]["response_text"]["value"]
            user = body["user"]["username"]
            self._handle_edited_approval(approval_id, edited_text, user, client)

        # ============== Conversational Message Handling ==============

        @self.app.event("app_mention")
        def handle_mention(event, client):
            """Handle when bot is mentioned - conversational response."""
            text = event.get("text", "")
            channel = event["channel"]
            user = event.get("user", "")

            # Remove the bot mention from the text
            clean_text = re.sub(r'<@[A-Z0-9]+>', '', text).strip()

            self._handle_conversation(clean_text, channel, user, client)

        @self.app.event("message")
        def handle_dm(event, client):
            """Handle direct messages to the bot."""
            # Only respond to DMs (channel type 'im')
            if event.get("channel_type") != "im":
                return

            # Ignore bot's own messages
            if event.get("bot_id"):
                return

            text = event.get("text", "")
            channel = event["channel"]
            user = event.get("user", "")

            self._handle_conversation(text, channel, user, client)

    def _handle_conversation(self, user_message: str, channel: str, user: str, client: WebClient):
        """Handle conversational messages using Claude to understand intent."""
        try:
            # Get current system state for context
            state = self._get_system_state()

            # Use Claude to understand what the user wants and generate response
            system_prompt = f"""You are a friendly assistant for an influencer marketing automation system.
You help users check on their influencer pipeline, pending approvals, and answer questions about the system.

Current system state:
{state}

Based on the user's message, provide a helpful, conversational response. Be concise but friendly.
If they're asking about status, approvals, or the pipeline - give them the relevant info from the state above.
If they want to see pending approvals, tell them you'll show the approval cards.
If they're asking how to do something, explain it simply.
If you're not sure what they want, ask clarifying questions.

Keep responses short and to the point - this is Slack, not email."""

            response = self.claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}]
            )

            bot_response = response.content[0].text

            # Check if we should also show approval cards
            show_approvals = self._should_show_approvals(user_message)

            # Send the conversational response
            client.chat_postMessage(
                channel=channel,
                text=bot_response,
            )

            # If they asked about approvals and there are pending ones, show the cards
            if show_approvals:
                pending = self.repo.get_pending_approvals()
                if pending:
                    self._send_approvals_to_channel(channel, client)

        except Exception as e:
            logger.error(f"Error in conversation handler: {e}")
            client.chat_postMessage(
                channel=channel,
                text="Sorry, I hit a snag. Try again or check the logs for details.",
            )

    def _should_show_approvals(self, message: str) -> bool:
        """Quick check if user is asking to see approvals."""
        keywords = ["approval", "pending", "review", "show me", "what's waiting", "queue"]
        message_lower = message.lower()
        return any(kw in message_lower for kw in keywords)

    def _get_system_state(self) -> str:
        """Get current system state as a string for Claude context."""
        try:
            # Count influencers by status
            status_counts = {}
            for status in InfluencerStatus:
                count = len(self.repo.get_influencers_by_status(status))
                if count > 0:
                    status_counts[status.value] = count

            pending_approvals = self.repo.get_pending_approvals()
            follow_ups = self.repo.get_conversations_needing_follow_up()

            # Build state string
            lines = ["Pipeline Status:"]
            if status_counts:
                for status, count in status_counts.items():
                    lines.append(f"  - {status.replace('_', ' ').title()}: {count}")
            else:
                lines.append("  - No influencers in pipeline yet")

            lines.append(f"\nPending Approvals: {len(pending_approvals)}")
            if pending_approvals:
                lines.append("Waiting for review:")
                for approval in pending_approvals[:5]:  # Show first 5
                    with self.repo.get_session() as session:
                        from ..database.models import PendingApproval
                        fresh = session.query(PendingApproval).filter(
                            PendingApproval.id == approval.id
                        ).first()
                        if fresh and fresh.conversation and fresh.conversation.influencer:
                            name = fresh.conversation.influencer.name
                            lines.append(f"  - {name}: {fresh.response_type}")

            lines.append(f"\nFollow-ups Needed: {len(follow_ups)}")

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Error getting system state: {e}")
            return "Unable to fetch current state."

    # ============== Action Handlers ==============

    def _handle_approval(self, approval_id: str, user: str, client: WebClient, body: dict):
        """Handle approval of a response."""
        try:
            approval = self.repo.approve_response(approval_id)
            if approval:
                logger.info(f"Response {approval_id} approved by {user}")

                # Trigger callback to send email
                if self.on_approval_callback:
                    self.on_approval_callback(approval)

                # Update the message to show it's been actioned
                self._update_card_status(
                    client,
                    body["channel"]["id"],
                    body["message"]["ts"],
                    approval_id,
                    f"✅ Approved and sent by @{user}",
                )

        except Exception as e:
            logger.error(f"Error handling approval: {e}")
            self._send_error(client, body["channel"]["id"], f"Error approving: {e}")

    def _handle_rejection(self, approval_id: str, user: str, client: WebClient, body: dict):
        """Handle rejection of a response."""
        try:
            self.repo.reject_response(approval_id)
            logger.info(f"Response {approval_id} rejected by {user}")

            self._update_card_status(
                client,
                body["channel"]["id"],
                body["message"]["ts"],
                approval_id,
                f"❌ Rejected by @{user}",
            )

        except Exception as e:
            logger.error(f"Error handling rejection: {e}")
            self._send_error(client, body["channel"]["id"], f"Error rejecting: {e}")

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

                # Notify in channel
                client.chat_postMessage(
                    channel=self.channel,
                    text=f"✏️ Response edited and sent by @{user}",
                )

        except Exception as e:
            logger.error(f"Error handling edited approval: {e}")

    def _handle_approve_all(self, user: str, client: WebClient, body: dict):
        """Handle bulk approval of all pending responses."""
        try:
            pending = self.repo.get_pending_approvals()
            approved_count = 0
            errors = []

            for approval in pending:
                try:
                    self.repo.approve_response(approval.id)
                    if self.on_approval_callback:
                        self.on_approval_callback(approval)
                    approved_count += 1
                except Exception as e:
                    errors.append(str(e))

            logger.info(f"{approved_count} responses approved by {user}")

            # Send confirmation
            msg = f"✅ {approved_count} responses approved and sent by @{user}"
            if errors:
                msg += f"\n⚠️ {len(errors)} errors occurred"

            client.chat_postMessage(
                channel=body["channel"]["id"],
                text=msg,
            )

        except Exception as e:
            logger.error(f"Error handling bulk approval: {e}")
            self._send_error(client, body["channel"]["id"], f"Error in bulk approval: {e}")

    # ============== Modal Handlers ==============

    def _open_edit_modal(self, approval_id: str, trigger_id: str, client: WebClient):
        """Open modal for editing a response."""
        try:
            # Get approval details from database
            with self.repo.get_session() as session:
                from ..database.models import PendingApproval
                approval = session.query(PendingApproval).filter(
                    PendingApproval.id == approval_id
                ).first()

                if not approval:
                    logger.error(f"Approval {approval_id} not found")
                    return

                # Get influencer info
                conv = approval.conversation
                influencer_name = conv.influencer.name if conv and conv.influencer else "Unknown"
                draft = approval.draft_response

            modal = {
                "type": "modal",
                "callback_id": "edit_modal",
                "private_metadata": approval_id,
                "title": {"type": "plain_text", "text": "Edit Response", "emoji": True},
                "submit": {"type": "plain_text", "text": "Save & Send", "emoji": True},
                "close": {"type": "plain_text", "text": "Cancel", "emoji": True},
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"✏️ Editing response to *{influencer_name}*",
                        },
                    },
                    {"type": "divider"},
                    {
                        "type": "input",
                        "block_id": "response_input",
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "response_text",
                            "multiline": True,
                            "initial_value": draft,
                            "min_length": 10,
                        },
                        "label": {"type": "plain_text", "text": "Email Response"},
                        "hint": {"type": "plain_text", "text": "Edit the email content below. It will be sent immediately after saving."},
                    },
                ],
            }

            client.views_open(trigger_id=trigger_id, view=modal)

        except SlackApiError as e:
            logger.error(f"Error opening edit modal: {e}")

    def _show_full_details(self, approval_id: str, trigger_id: str, client: WebClient):
        """Show full details in a modal."""
        try:
            with self.repo.get_session() as session:
                from ..database.models import PendingApproval
                approval = session.query(PendingApproval).filter(
                    PendingApproval.id == approval_id
                ).first()

                if not approval:
                    return

                conv = approval.conversation
                influencer = conv.influencer if conv else None

                # Build detail blocks
                influencer_info = (
                    f"*Name:* {influencer.name if influencer else 'Unknown'}\n"
                    f"*Email:* {influencer.email if influencer else 'Unknown'}\n"
                    f"*Platform:* {influencer.platform or 'N/A'}\n"
                    f"*Handle:* @{influencer.handle or 'N/A'}\n"
                    f"*Followers:* {influencer.follower_count:,}" if influencer and influencer.follower_count else "N/A"
                )

                their_message = approval.their_last_message or "No message recorded"
                our_response = approval.draft_response

            modal = {
                "type": "modal",
                "title": {"type": "plain_text", "text": "Full Details", "emoji": True},
                "close": {"type": "plain_text", "text": "Close", "emoji": True},
                "blocks": [
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": "👤 Influencer Info", "emoji": True},
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": influencer_info},
                    },
                    {"type": "divider"},
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": "📩 Their Message", "emoji": True},
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": their_message[:2900]},  # Slack limit
                    },
                    {"type": "divider"},
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": "📤 Our Drafted Response", "emoji": True},
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": our_response[:2900]},
                    },
                ],
            }

            client.views_open(trigger_id=trigger_id, view=modal)

        except SlackApiError as e:
            logger.error(f"Error opening details modal: {e}")

    # ============== Helper Methods ==============

    def _send_approvals_to_channel(self, channel: str, client: WebClient):
        """Send pending approvals to a channel."""
        pending = self.repo.get_pending_approvals()

        if not pending:
            client.chat_postMessage(
                channel=channel,
                text="✅ No pending approvals - you're all caught up!",
            )
            return

        # Build approval data
        approvals_data = []
        for approval in pending:
            with self.repo.get_session() as session:
                from ..database.models import PendingApproval
                fresh_approval = session.query(PendingApproval).filter(
                    PendingApproval.id == approval.id
                ).first()

                if fresh_approval:
                    conv = fresh_approval.conversation
                    influencer = conv.influencer if conv else None

                    approvals_data.append({
                        "id": fresh_approval.id,
                        "influencer_name": influencer.name if influencer else "Unknown",
                        "influencer_handle": influencer.handle if influencer else None,
                        "their_message": fresh_approval.their_last_message or "",
                        "draft_response": fresh_approval.draft_response,
                        "response_type": fresh_approval.response_type,
                        "their_rate": fresh_approval.their_rate,
                        "our_counter": fresh_approval.our_counter,
                        "priority": fresh_approval.priority,
                    })

        blocks = MessageBuilder.build_approval_batch(approvals_data)

        try:
            client.chat_postMessage(
                channel=channel,
                text=f"{len(pending)} responses ready for approval",
                blocks=blocks,
            )
        except SlackApiError as e:
            logger.error(f"Error sending approvals: {e}")

    def _update_card_status(
        self, client: WebClient, channel: str, ts: str, approval_id: str, status_text: str
    ):
        """Update an approval card to show it's been actioned."""
        try:
            client.chat_update(
                channel=channel,
                ts=ts,
                text=status_text,
                blocks=[
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": status_text},
                    },
                    {
                        "type": "context",
                        "elements": [
                            {"type": "mrkdwn", "text": f"_Approval ID: {approval_id[:8]}..._"},
                        ],
                    },
                ],
            )
        except SlackApiError as e:
            logger.error(f"Error updating card: {e}")

    def _send_error(self, client: WebClient, channel: str, message: str):
        """Send an error message."""
        try:
            client.chat_postMessage(
                channel=channel,
                text=f"⚠️ {message}",
            )
        except SlackApiError:
            pass

    # ============== Public Methods ==============

    def send_approval_batch(self) -> bool:
        """Send pending approvals to Slack for review."""
        pending = self.repo.get_pending_approvals()

        if not pending:
            logger.info("No pending approvals to send")
            return True

        logger.info(f"Sending {len(pending)} approvals to Slack")
        self._send_approvals_to_channel(self.channel, self.client)
        return True

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

    def send_notification(self, message: str, priority: str = "normal") -> bool:
        """Send a notification message."""
        try:
            emoji = "🔔" if priority == "normal" else "🚨"
            self.client.chat_postMessage(
                channel=self.channel,
                text=f"{emoji} {message}",
            )
            return True
        except SlackApiError as e:
            logger.error(f"Error sending notification: {e}")
            return False

    def send_single_approval(self, approval_id: str) -> bool:
        """Send a single approval card to the channel."""
        try:
            with self.repo.get_session() as session:
                from ..database.models import PendingApproval
                approval = session.query(PendingApproval).filter(
                    PendingApproval.id == approval_id
                ).first()

                if not approval:
                    return False

                conv = approval.conversation
                influencer = conv.influencer if conv else None

                approval_data = {
                    "id": approval.id,
                    "influencer_name": influencer.name if influencer else "Unknown",
                    "influencer_handle": influencer.handle if influencer else None,
                    "their_message": approval.their_last_message or "",
                    "draft_response": approval.draft_response,
                    "response_type": approval.response_type,
                    "their_rate": approval.their_rate,
                    "our_counter": approval.our_counter,
                    "priority": approval.priority,
                }

            blocks = MessageBuilder.build_approval_card(**approval_data)

            self.client.chat_postMessage(
                channel=self.channel,
                text=f"New approval needed for {approval_data['influencer_name']}",
                blocks=blocks,
            )
            return True

        except Exception as e:
            logger.error(f"Error sending single approval: {e}")
            return False

    def start(self):
        """Start the Slack bot in socket mode."""
        if not self.settings.slack_app_token:
            raise ValueError(
                "SLACK_APP_TOKEN is required for Socket Mode. "
                "Get it from your Slack app settings under 'Socket Mode'."
            )

        handler = SocketModeHandler(self.app, self.settings.slack_app_token)
        logger.info("Starting Slack bot in Socket Mode...")
        logger.info(f"Listening in channel: {self.channel}")
        handler.start()
