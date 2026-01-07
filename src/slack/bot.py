"""Enhanced Slack bot for Customuse influencer workflow with rich interactions."""

import re
import json
from typing import Optional, Callable
from datetime import datetime

import anthropic
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from .messages import MessageBuilder
from ..database.repository import Repository, get_repository
from ..database.models import ApprovalStatus, InfluencerStatus, PendingApproval
from ..ai.responder import ResponseGenerator, DraftResponse
from ..utils.config import get_settings, get_app_config
from ..utils.logging import get_logger

logger = get_logger("slack")


class SlackBot:
    """Enhanced Slack bot with rich approval cards and input flows."""

    def __init__(
        self,
        repository: Optional[Repository] = None,
        on_approval_callback: Optional[Callable] = None,
        email_processor: Optional[object] = None,
    ):
        self.settings = get_settings()
        self.app_config = get_app_config()
        self.repo = repository or get_repository()
        self.on_approval_callback = on_approval_callback
        self.email_processor = email_processor  # For manual email checks

        # Initialize Claude client for conversational understanding
        self.claude = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)

        # Initialize response generator for re-generating drafts
        self.responder = ResponseGenerator()

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

        # ============== NEW: Input/Adjustment Actions ==============

        @self.app.action("provide_input")
        def handle_provide_input(ack, body, client):
            """Open modal to provide missing inputs (promo code, deadline, etc.)."""
            ack()
            approval_id = body["actions"][0]["value"]
            self._open_input_modal(approval_id, body["trigger_id"], client)

        @self.app.action("adjust_offer")
        def handle_adjust_offer(ack, body, client):
            """Open modal to adjust the offer amount."""
            ack()
            approval_id = body["actions"][0]["value"]
            self._open_adjust_offer_modal(approval_id, body["trigger_id"], client)

        @self.app.action("switch_to_performance")
        def handle_switch_to_performance(ack, body, client):
            """Switch from flat fee to performance-based offer."""
            ack()
            approval_id = body["actions"][0]["value"]
            user = body["user"]["username"]
            self._handle_switch_to_performance(approval_id, user, client, body)

        # ============== Modal Submissions ==============

        @self.app.view("edit_modal")
        def handle_edit_modal_submission(ack, body, client, view):
            ack()
            approval_id = view["private_metadata"]
            edited_text = view["state"]["values"]["response_input"]["response_text"]["value"]
            user = body["user"]["username"]
            self._handle_edited_approval(approval_id, edited_text, user, client)

        @self.app.view("input_modal")
        def handle_input_modal_submission(ack, body, client, view):
            """Handle submission of the input modal (promo codes, deadlines, etc.)."""
            ack()
            approval_id = view["private_metadata"]
            user = body["user"]["username"]

            # Extract input values from the modal
            inputs = {}
            state_values = view["state"]["values"]

            for block_id, block_data in state_values.items():
                if block_id.startswith("input_"):
                    field_name = block_id.replace("input_", "")
                    action_id = f"value_{field_name}"
                    if action_id in block_data:
                        inputs[field_name] = block_data[action_id]["value"]

            self._handle_input_submission(approval_id, inputs, user, client)

        @self.app.view("adjust_offer_modal")
        def handle_adjust_offer_modal_submission(ack, body, client, view):
            """Handle submission of the adjust offer modal."""
            ack()
            approval_id = view["private_metadata"]
            user = body["user"]["username"]

            new_offer_str = view["state"]["values"]["new_offer"]["offer_value"]["value"]
            try:
                new_offer = float(new_offer_str.replace("$", "").replace(",", "").strip())
            except ValueError:
                client.chat_postMessage(
                    channel=self.channel,
                    text=f"⚠️ Invalid offer amount: {new_offer_str}",
                )
                return

            self._handle_offer_adjustment(approval_id, new_offer, user, client)

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

    # ============== NEW: Input Handling Methods ==============

    def _open_input_modal(self, approval_id: str, trigger_id: str, client: WebClient):
        """Open modal to provide missing inputs."""
        try:
            with self.repo.get_session() as session:
                approval = session.query(PendingApproval).filter(
                    PendingApproval.id == approval_id
                ).first()

                if not approval:
                    logger.error(f"Approval {approval_id} not found")
                    return

                conv = approval.conversation
                influencer_name = conv.influencer.name if conv and conv.influencer else "Unknown"

                # Parse needs_input from the stored JSON or default
                needs_input = []
                extra_data = getattr(approval, 'extra_data', None)
                if extra_data:
                    try:
                        extra = json.loads(extra_data) if isinstance(extra_data, str) else extra_data
                        needs_input = extra.get("needs_input", [])
                    except (json.JSONDecodeError, TypeError):
                        pass

                # If no stored needs_input, infer from placeholders in draft
                if not needs_input:
                    draft = approval.draft_response or ""
                    if "{{NEEDS_PROMO_CODE}}" in draft or "{{promo_code}}" in draft:
                        needs_input.append({"field": "promo_code", "description": "Unique promo code", "type": "text"})
                    if "{{NEEDS_DEADLINE}}" in draft or "{{preview_deadline}}" in draft:
                        needs_input.append({"field": "preview_deadline", "description": "Preview deadline", "type": "text"})
                    if "{{NEEDS_FEEDBACK}}" in draft:
                        needs_input.append({"field": "feedback", "description": "Feedback", "type": "text"})

                modal = MessageBuilder.build_input_modal(
                    approval_id=approval_id,
                    influencer_name=influencer_name,
                    needs_input=needs_input,
                    current_draft=approval.draft_response or "",
                )

            client.views_open(trigger_id=trigger_id, view=modal)

        except SlackApiError as e:
            logger.error(f"Error opening input modal: {e}")

    def _handle_input_submission(
        self, approval_id: str, inputs: dict, user: str, client: WebClient
    ):
        """Apply user inputs to the draft and approve."""
        try:
            with self.repo.get_session() as session:
                approval = session.query(PendingApproval).filter(
                    PendingApproval.id == approval_id
                ).first()

                if not approval:
                    logger.error(f"Approval {approval_id} not found")
                    return

                # Get draft and apply inputs
                draft = approval.draft_response or ""

                # Replace placeholders with provided values
                for field, value in inputs.items():
                    placeholders = [
                        f"{{{{{field}}}}}",
                        f"{{{{NEEDS_{field.upper()}}}}}",
                        f"{{{{needs_{field}}}}}",
                    ]
                    for placeholder in placeholders:
                        draft = draft.replace(placeholder, value)

                # Update the approval with the filled draft
                approval.draft_response = draft
                session.commit()

                # Get influencer name for notification
                conv = approval.conversation
                influencer_name = conv.influencer.name if conv and conv.influencer else "Unknown"

            # Now approve and send
            self._handle_approval_internal(approval_id, user, client, f"with inputs: {', '.join(inputs.keys())}")

        except Exception as e:
            logger.error(f"Error handling input submission: {e}")
            client.chat_postMessage(
                channel=self.channel,
                text=f"⚠️ Error applying inputs: {e}",
            )

    def _open_adjust_offer_modal(self, approval_id: str, trigger_id: str, client: WebClient):
        """Open modal to adjust offer amount."""
        try:
            with self.repo.get_session() as session:
                approval = session.query(PendingApproval).filter(
                    PendingApproval.id == approval_id
                ).first()

                if not approval:
                    return

                conv = approval.conversation
                influencer_name = conv.influencer.name if conv and conv.influencer else "Unknown"

                modal = MessageBuilder.build_adjust_offer_modal(
                    approval_id=approval_id,
                    influencer_name=influencer_name,
                    current_offer=approval.our_counter,
                    their_rate=approval.their_rate,
                )

            client.views_open(trigger_id=trigger_id, view=modal)

        except SlackApiError as e:
            logger.error(f"Error opening adjust offer modal: {e}")

    def _handle_offer_adjustment(
        self, approval_id: str, new_offer: float, user: str, client: WebClient
    ):
        """Regenerate draft with adjusted offer amount."""
        try:
            with self.repo.get_session() as session:
                approval = session.query(PendingApproval).filter(
                    PendingApproval.id == approval_id
                ).first()

                if not approval:
                    return

                conv = approval.conversation
                influencer = conv.influencer if conv else None
                influencer_name = influencer.name if influencer else "Unknown"

                # Generate new draft with updated offer
                new_draft = self.responder.generate_counter_offer(
                    influencer_name=influencer_name,
                    their_rate=approval.their_rate or 0,
                    our_counter=new_offer,
                    use_performance=False,
                )

                # Update approval with new draft
                approval.draft_response = new_draft.body
                approval.our_counter = new_offer
                session.commit()

            # Notify in channel
            client.chat_postMessage(
                channel=self.channel,
                text=f"🔄 @{user} adjusted offer for *{influencer_name}* to *${new_offer:,.0f}*. Review updated draft above.",
            )

            # Re-send the approval card with updated info
            self.send_single_approval(approval_id)

        except Exception as e:
            logger.error(f"Error adjusting offer: {e}")
            client.chat_postMessage(
                channel=self.channel,
                text=f"⚠️ Error adjusting offer: {e}",
            )

    def _handle_switch_to_performance(
        self, approval_id: str, user: str, client: WebClient, body: dict
    ):
        """Switch from flat fee to performance-based offer."""
        try:
            with self.repo.get_session() as session:
                approval = session.query(PendingApproval).filter(
                    PendingApproval.id == approval_id
                ).first()

                if not approval:
                    return

                conv = approval.conversation
                influencer = conv.influencer if conv else None
                influencer_name = influencer.name if influencer else "Unknown"

                # Generate performance-based draft
                new_draft = self.responder.generate_counter_offer(
                    influencer_name=influencer_name,
                    their_rate=approval.their_rate or 0,
                    our_counter=approval.our_counter or 100,
                    use_performance=True,
                )

                # Update approval
                approval.draft_response = new_draft.body
                approval.response_type = "counter_offer_performance"
                session.commit()

            # Notify and re-send card
            client.chat_postMessage(
                channel=self.channel,
                text=f"📊 @{user} switched to *performance-based offer* for *{influencer_name}*.",
            )

            self.send_single_approval(approval_id)

        except Exception as e:
            logger.error(f"Error switching to performance: {e}")

    # ============== Conversation Handling ==============

    def _handle_conversation(self, user_message: str, channel: str, user: str, client: WebClient):
        """Handle conversational messages using Claude to understand intent."""
        message_lower = user_message.lower().strip()

        # ========== QUICK COMMANDS (no Claude needed) ==========

        # Ping / status check
        if any(kw in message_lower for kw in ["ping", "alive", "you there", "hello", "hi", "status", "are you on"]):
            pending_count = len(self.repo.get_pending_approvals())
            client.chat_postMessage(
                channel=channel,
                text=f"I'm online and running. {pending_count} pending approval(s) in queue.",
            )
            return

        # Manual email check
        if any(kw in message_lower for kw in ["check email", "check mail", "scan email", "fetch email", "check inbox", "scan inbox"]):
            self._handle_manual_email_check(channel, client)
            return

        # Direct command to show approval cards (bypass Claude)
        if any(kw in message_lower for kw in ["show cards", "show drafts", "display cards", "display drafts", "send cards", "show approvals", "display approvals"]):
            pending = self.repo.get_pending_approvals()
            if pending:
                client.chat_postMessage(
                    channel=channel,
                    text=f"📋 Sending {len(pending)} approval card(s)...",
                )
                self._send_approvals_to_channel(channel, client)
            else:
                client.chat_postMessage(
                    channel=channel,
                    text="No pending approvals to show.",
                )
            return

        # Database debug command
        if any(kw in message_lower for kw in ["debug db", "debug database", "db stats", "database stats"]):
            self._handle_debug_db(channel, client)
            return

        # ========== CLAUDE-POWERED RESPONSES ==========
        try:
            # Get current system state for context
            state = self._get_system_state()

            # Use Claude to understand what the user wants
            system_prompt = f"""You are a friendly assistant for Pauline's influencer marketing automation system at Customuse.
You help check on the pipeline, pending approvals, and answer questions.

Current state:
{state}

Based on Pauline's message, provide a helpful, conversational response. Be concise - this is Slack.
If she's asking about approvals, status, or the pipeline - give her the relevant info.
If she wants to see pending approvals, tell her you'll show the approval cards.
If she's asking how to do something, explain simply.

Keep responses short and friendly."""

            response = self.claude.messages.create(
                model="claude-3-5-haiku-20241022",  # Haiku for cost-effective chat
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

    def _handle_manual_email_check(self, channel: str, client: WebClient):
        """Manually trigger an email check."""
        client.chat_postMessage(
            channel=channel,
            text="Checking inbox now...",
        )

        if not self.email_processor:
            client.chat_postMessage(
                channel=channel,
                text="Email processor not available. Try redeploying.",
            )
            return

        try:
            processed = self.email_processor.process_new_emails()
            if processed:
                client.chat_postMessage(
                    channel=channel,
                    text=f"Found and processed {len(processed)} new email(s). Check above for any new approval cards.",
                )
                # Send approval cards if any were created
                self._send_approvals_to_channel(channel, client)
            else:
                client.chat_postMessage(
                    channel=channel,
                    text="No new influencer emails found.",
                )
        except Exception as e:
            logger.error(f"Error in manual email check: {e}")
            client.chat_postMessage(
                channel=channel,
                text=f"Error checking emails: {str(e)[:100]}",
            )

    def _handle_debug_db(self, channel: str, client: WebClient):
        """Show database statistics for debugging."""
        try:
            from ..database.models import Influencer, Conversation, Email, PendingApproval
            from sqlalchemy import func

            with self.repo.get_session() as session:
                # Count records in each table
                influencer_count = session.query(func.count(Influencer.id)).scalar()
                conversation_count = session.query(func.count(Conversation.id)).scalar()
                email_count = session.query(func.count(Email.id)).scalar()
                pending_count = session.query(func.count(PendingApproval.id)).filter(
                    PendingApproval.status == ApprovalStatus.PENDING
                ).scalar()
                total_approval_count = session.query(func.count(PendingApproval.id)).scalar()

                # Get database URL (masked)
                db_url = self.repo.database_url
                if "://" in db_url:
                    db_type = db_url.split("://")[0]
                    if "@" in db_url:
                        # Mask credentials
                        db_display = f"{db_type}://***@{db_url.split('@')[-1][:30]}..."
                    else:
                        db_display = f"{db_type}://{db_url.split('://')[-1][:30]}..."
                else:
                    db_display = db_url[:50]

            debug_text = f"""🔧 *Database Debug Info*
• Type: `{db_display}`
• Influencers: {influencer_count}
• Conversations: {conversation_count}
• Emails: {email_count}
• Pending Approvals: {pending_count}
• Total Approvals (all statuses): {total_approval_count}

_If counts are 0 after processing emails, the database may have been wiped on deploy. Use PostgreSQL for persistence._"""

            client.chat_postMessage(
                channel=channel,
                text=debug_text,
            )
        except Exception as e:
            logger.error(f"Error in debug db: {e}")
            client.chat_postMessage(
                channel=channel,
                text=f"Error getting DB stats: {str(e)[:100]}",
            )

    def _should_show_approvals(self, message: str) -> bool:
        """Quick check if user is asking to see approvals."""
        keywords = ["approval", "pending", "review", "show me", "what's waiting", "queue", "drafts"]
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
                for approval in pending_approvals[:5]:
                    with self.repo.get_session() as session:
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
        self._handle_approval_internal(approval_id, user, client)
        # Update the message to show it's been actioned
        self._update_card_status(
            client,
            body["channel"]["id"],
            body["message"]["ts"],
            approval_id,
            f"✅ Approved and sent by @{user}",
        )

    def _handle_approval_internal(
        self, approval_id: str, user: str, client: WebClient, extra_info: str = ""
    ):
        """Internal approval handler."""
        try:
            approval = self.repo.approve_response(approval_id)
            if approval:
                logger.info(f"Response {approval_id} approved by {user} {extra_info}")

                # Trigger callback to send email
                if self.on_approval_callback:
                    self.on_approval_callback(approval)

        except Exception as e:
            logger.error(f"Error handling approval: {e}")
            client.chat_postMessage(
                channel=self.channel,
                text=f"⚠️ Error approving: {e}",
            )

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

            # Filter out any that need input
            ready_to_send = []
            needs_input = []

            for approval in pending:
                with self.repo.get_session() as session:
                    fresh = session.query(PendingApproval).filter(
                        PendingApproval.id == approval.id
                    ).first()
                    if fresh:
                        draft = fresh.draft_response or ""
                        if "{{NEEDS_" in draft or "{{promo_code}}" in draft or "{{preview_deadline}}" in draft:
                            needs_input.append(fresh.id)
                        else:
                            ready_to_send.append(fresh.id)

            approved_count = 0
            errors = []

            for approval_id in ready_to_send:
                try:
                    approval = self.repo.approve_response(approval_id)
                    if self.on_approval_callback and approval:
                        self.on_approval_callback(approval)
                    approved_count += 1
                except Exception as e:
                    errors.append(str(e))

            logger.info(f"{approved_count} responses approved by {user}")

            # Send confirmation
            msg = f"✅ {approved_count} responses approved and sent by @{user}"
            if needs_input:
                msg += f"\n⚠️ {len(needs_input)} responses need additional info before sending"
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
            with self.repo.get_session() as session:
                approval = session.query(PendingApproval).filter(
                    PendingApproval.id == approval_id
                ).first()

                if not approval:
                    logger.error(f"Approval {approval_id} not found")
                    return

                conv = approval.conversation
                influencer_name = conv.influencer.name if conv and conv.influencer else "Unknown"
                draft = approval.draft_response

            modal = MessageBuilder.build_edit_modal(
                approval_id=approval_id,
                influencer_name=influencer_name,
                current_draft=draft or "",
            )

            client.views_open(trigger_id=trigger_id, view=modal)

        except SlackApiError as e:
            logger.error(f"Error opening edit modal: {e}")

    def _show_full_details(self, approval_id: str, trigger_id: str, client: WebClient):
        """Show full details in a modal."""
        try:
            with self.repo.get_session() as session:
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
                    f"*Handle:* @{influencer.handle or 'N/A'}"
                )

                their_message = approval.their_last_message or "No message recorded"
                our_response = approval.draft_response or ""

                # Pricing info
                pricing_info = ""
                if approval.their_rate:
                    pricing_info += f"*Their ask:* ${approval.their_rate:,.0f}\n"
                if approval.our_counter:
                    pricing_info += f"*Our offer:* ${approval.our_counter:,.0f}\n"

            modal_blocks = [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "👤 Influencer Info", "emoji": True},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": influencer_info},
                },
            ]

            if pricing_info:
                modal_blocks.extend([
                    {"type": "divider"},
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": "💰 Pricing", "emoji": True},
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": pricing_info},
                    },
                ])

            modal_blocks.extend([
                {"type": "divider"},
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "📩 Their Message", "emoji": True},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": their_message[:2900]},
                },
                {"type": "divider"},
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "📤 Our Drafted Response", "emoji": True},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"```{our_response[:2800]}```"},
                },
            ])

            modal = {
                "type": "modal",
                "title": {"type": "plain_text", "text": "Full Details", "emoji": True},
                "close": {"type": "plain_text", "text": "Close", "emoji": True},
                "blocks": modal_blocks,
            }

            client.views_open(trigger_id=trigger_id, view=modal)

        except SlackApiError as e:
            logger.error(f"Error opening details modal: {e}")

    # ============== Helper Methods ==============

    def _send_approvals_to_channel(self, channel: str, client: WebClient):
        """Send pending approvals to a channel in batches (Slack has 50 block limit)."""
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
                fresh_approval = session.query(PendingApproval).filter(
                    PendingApproval.id == approval.id
                ).first()

                if fresh_approval:
                    conv = fresh_approval.conversation
                    influencer = conv.influencer if conv else None

                    # Check for needs_input from extra_data or infer from placeholders
                    needs_input = []
                    draft = fresh_approval.draft_response or ""
                    extra_data = getattr(fresh_approval, 'extra_data', None)

                    if extra_data:
                        try:
                            extra = json.loads(extra_data) if isinstance(extra_data, str) else extra_data
                            needs_input = extra.get("needs_input", [])
                        except (json.JSONDecodeError, TypeError):
                            pass

                    # Infer from placeholders if not set
                    if not needs_input:
                        if "{{NEEDS_PROMO_CODE}}" in draft or "{{promo_code}}" in draft:
                            needs_input.append({"field": "promo_code", "description": "Unique promo code"})
                        if "{{NEEDS_DEADLINE}}" in draft or "{{preview_deadline}}" in draft:
                            needs_input.append({"field": "preview_deadline", "description": "Preview deadline"})
                        if "{{NEEDS_FEEDBACK}}" in draft:
                            needs_input.append({"field": "feedback", "description": "Feedback"})

                    approvals_data.append({
                        "id": fresh_approval.id,
                        "influencer_name": influencer.name if influencer else "Unknown",
                        "influencer_handle": influencer.handle if influencer else None,
                        "their_message": fresh_approval.their_last_message or "",
                        "draft_response": draft,
                        "response_type": fresh_approval.response_type,
                        "their_rate": fresh_approval.their_rate,
                        "our_counter": fresh_approval.our_counter,
                        "priority": fresh_approval.priority,
                        "needs_input": needs_input if needs_input else None,
                        "template_used": fresh_approval.response_type,
                        "platform": influencer.platform if influencer else None,
                    })

        # Send in batches of 5 approvals (each card ~8-10 blocks, Slack limit is 50)
        BATCH_SIZE = 5
        total = len(approvals_data)

        for i in range(0, total, BATCH_SIZE):
            batch = approvals_data[i:i + BATCH_SIZE]
            batch_num = (i // BATCH_SIZE) + 1
            total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

            blocks = MessageBuilder.build_approval_batch(batch)

            try:
                header = f"📋 Approvals {i + 1}-{min(i + BATCH_SIZE, total)} of {total}"
                if total_batches > 1:
                    header += f" (batch {batch_num}/{total_batches})"

                client.chat_postMessage(
                    channel=channel,
                    text=header,
                    blocks=blocks,
                )
            except SlackApiError as e:
                logger.error(f"Error sending approvals batch {batch_num}: {e}")

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
                approval = session.query(PendingApproval).filter(
                    PendingApproval.id == approval_id
                ).first()

                if not approval:
                    return False

                conv = approval.conversation
                influencer = conv.influencer if conv else None

                # Check for needs_input
                needs_input = []
                draft = approval.draft_response or ""
                extra_data = getattr(approval, 'extra_data', None)

                if extra_data:
                    try:
                        extra = json.loads(extra_data) if isinstance(extra_data, str) else extra_data
                        needs_input = extra.get("needs_input", [])
                    except (json.JSONDecodeError, TypeError):
                        pass

                if not needs_input:
                    if "{{NEEDS_PROMO_CODE}}" in draft or "{{promo_code}}" in draft:
                        needs_input.append({"field": "promo_code", "description": "Unique promo code"})
                    if "{{NEEDS_DEADLINE}}" in draft:
                        needs_input.append({"field": "preview_deadline", "description": "Preview deadline"})

                approval_data = {
                    "id": approval.id,
                    "influencer_name": influencer.name if influencer else "Unknown",
                    "influencer_handle": influencer.handle if influencer else None,
                    "their_message": approval.their_last_message or "",
                    "draft_response": draft,
                    "response_type": approval.response_type,
                    "their_rate": approval.their_rate,
                    "our_counter": approval.our_counter,
                    "priority": approval.priority,
                    "needs_input": needs_input if needs_input else None,
                    "platform": influencer.platform if influencer else None,
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
