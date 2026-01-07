"""Email processing logic - coordinates Gmail and Claude for handling emails."""

from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass

from .gmail_client import GmailClient, EmailMessage
from .filter import EmailFilter, get_email_filter
from ..database.repository import Repository, get_repository
from ..database.models import (
    InfluencerStatus,
    ConversationStatus,
    Conversation,
    Influencer,
)
from ..ai.classifier import EmailClassifier, ClassificationResult
from ..ai.responder import ResponseGenerator
from ..utils.config import get_app_config, PricingConfig
from ..utils.logging import get_logger

logger = get_logger("processor")


@dataclass
class ProcessedEmail:
    """Result of processing an email."""

    email_id: str
    conversation_id: str
    influencer_id: str
    classification: ClassificationResult
    draft_response: Optional[str]
    requires_approval: bool
    auto_approved: bool
    action_taken: str


class EmailProcessor:
    """Processes incoming emails through classification and response generation."""

    def __init__(
        self,
        gmail_client: Optional[GmailClient] = None,
        repository: Optional[Repository] = None,
        classifier: Optional[EmailClassifier] = None,
        responder: Optional[ResponseGenerator] = None,
        email_filter: Optional[EmailFilter] = None,
    ):
        self.gmail = gmail_client or GmailClient()
        self.repo = repository or get_repository()
        self.classifier = classifier or EmailClassifier()
        self.responder = responder or ResponseGenerator()
        self.email_filter = email_filter or get_email_filter()
        self.pricing = PricingConfig()
        self.config = get_app_config()

    def process_new_emails(self) -> list[ProcessedEmail]:
        """Check for and process new unread emails."""
        logger.info("Checking for new emails...")

        if not self.gmail.service:
            if not self.gmail.authenticate():
                logger.error("Failed to authenticate with Gmail")
                return []

        # Get unread messages
        messages = self.gmail.get_unread_messages(max_results=10)
        logger.info(f"Found {len(messages)} unread messages")

        processed = []
        skipped = 0

        for message in messages:
            # ========== FILTERING STEP ==========
            # Check if this email should be processed at all
            filter_result = self.email_filter.should_process(
                from_email=message.from_email,
                subject=message.subject,
                body=message.body,
                thread_id=message.thread_id,
            )

            if not filter_result.should_process:
                logger.debug(
                    f"Skipping email from {message.from_email}: {filter_result.reason}"
                )
                skipped += 1
                # Mark as read so we don't check it again
                self.gmail.mark_as_read(message.message_id)
                continue

            logger.info(
                f"Processing email from {message.from_email}: {filter_result.reason}"
            )

            # ========== PROCESSING STEP ==========
            result = self._process_single_email(message)
            if result:
                processed.append(result)
                # Mark as read after processing
                self.gmail.mark_as_read(message.message_id)

        logger.info(f"Processed {len(processed)} emails, skipped {skipped} non-influencer emails")
        return processed

    def _process_single_email(self, message: EmailMessage) -> Optional[ProcessedEmail]:
        """Process a single email message."""
        logger.info(f"Processing email from {message.from_email}: {message.subject}")

        # Check if we've already processed this email
        existing = self.repo.get_email_by_message_id(message.message_id)
        if existing:
            logger.debug(f"Email {message.message_id} already processed, skipping")
            return None

        # Find or create influencer
        influencer = self._get_or_create_influencer(message.from_email)
        if not influencer:
            logger.warning(f"Could not identify influencer for {message.from_email}")
            return None

        # Find or create conversation
        conversation = self._get_or_create_conversation(
            influencer.id, message.thread_id, message.subject
        )

        # Store the email
        email_record = self.repo.create_email(
            conversation_id=conversation.id,
            gmail_message_id=message.message_id,
            direction="inbound",
            from_email=message.from_email,
            to_email=message.to_email,
            subject=message.subject,
            body=message.body,
            body_html=message.body_html,
            sent_at=message.date,
        )

        # Get conversation history for context
        history = self.repo.get_conversation_emails(conversation.id)

        # Classify the email
        classification = self.classifier.classify(
            email_body=message.body,
            email_subject=message.subject,
            conversation_history=[
                {"direction": e.direction, "body": e.body} for e in history
            ],
        )

        # Update email with classification
        self.repo.update_email_classification(
            email_id=email_record.id,
            intent=classification.intent,
            confidence=classification.confidence,
            extracted_data=classification.extracted_data,
        )

        logger.info(
            f"Classified as '{classification.intent}' "
            f"(confidence: {classification.confidence:.2f})"
        )

        # Update conversation status
        self.repo.update_conversation_after_message(
            conversation_id=conversation.id, message_from="them"
        )

        # Generate response based on classification
        result = self._handle_classification(
            influencer=influencer,
            conversation=conversation,
            classification=classification,
            original_message=message,
        )

        return result

    def _get_or_create_influencer(self, email: str) -> Optional[Influencer]:
        """Get existing influencer or create a new one."""
        influencer = self.repo.get_influencer_by_email(email)

        if not influencer:
            # For now, create a basic record. In production, you might
            # want to skip unknown senders or require them to be pre-registered.
            logger.info(f"Creating new influencer record for {email}")
            influencer = self.repo.create_influencer(
                email=email,
                name=email.split("@")[0],  # Placeholder name
            )

        return influencer

    def _get_or_create_conversation(
        self, influencer_id: str, thread_id: str, subject: str
    ) -> Conversation:
        """Get existing conversation or create a new one."""
        conversation = self.repo.get_conversation_by_thread_id(thread_id)

        if not conversation:
            conversation = self.repo.create_conversation(
                influencer_id=influencer_id,
                gmail_thread_id=thread_id,
                subject=subject,
            )

        return conversation

    def _handle_classification(
        self,
        influencer: Influencer,
        conversation: Conversation,
        classification: ClassificationResult,
        original_message: EmailMessage,
    ) -> ProcessedEmail:
        """Handle email based on its classification."""
        intent = classification.intent
        draft_response = None
        requires_approval = True
        auto_approved = False
        action_taken = "pending_review"

        # Handle different intents
        if intent == "accepting_offer":
            action_taken = "deal_accepted"
            self.repo.update_influencer_status(influencer.id, InfluencerStatus.AGREED)
            draft_response = self.responder.generate_deal_confirmation(
                influencer_name=influencer.name,
                agreed_rate=influencer.current_offer or influencer.initial_rate_offered,
            )
            # Record the acceptance
            self.repo.record_negotiation_event(
                conversation_id=conversation.id,
                event_type="accept",
                our_amount=influencer.current_offer,
                their_amount=classification.extracted_data.get("agreed_rate"),
            )

        elif intent == "negotiating_price":
            their_rate = classification.extracted_data.get("requested_rate")
            action_taken = "counter_offer_drafted"

            if their_rate:
                # Calculate our counter
                our_counter = self._calculate_counter_offer(
                    their_rate=their_rate,
                    initial_offer=influencer.initial_rate_offered,
                    current_offer=influencer.current_offer,
                )

                # Check if auto-approve
                if self.pricing.should_auto_approve(our_counter):
                    auto_approved = True
                    requires_approval = False
                    action_taken = "auto_approved_counter"

                # Check if escalation needed
                if self.pricing.should_escalate(their_rate):
                    action_taken = "escalated_to_human"
                    requires_approval = True

                draft_response = self.responder.generate_counter_offer(
                    influencer_name=influencer.name,
                    their_rate=their_rate,
                    our_counter=our_counter,
                )

                # Record the negotiation event
                self.repo.record_negotiation_event(
                    conversation_id=conversation.id,
                    event_type="counter",
                    our_amount=our_counter,
                    their_amount=their_rate,
                )

        elif intent == "asking_question":
            question_type = classification.extracted_data.get("question_type", "general")
            draft_response = self.responder.generate_question_response(
                influencer_name=influencer.name,
                question_type=question_type,
                question_content=original_message.body,
            )
            action_taken = "question_response_drafted"

        elif intent == "declining_offer":
            action_taken = "declined"
            self.repo.update_influencer_status(influencer.id, InfluencerStatus.DECLINED)
            requires_approval = False  # No response needed

        elif intent == "submitting_content":
            action_taken = "content_received"
            self.repo.update_influencer_status(
                influencer.id, InfluencerStatus.CONTENT_RECEIVED
            )
            draft_response = self.responder.generate_content_received_response(
                influencer_name=influencer.name
            )

        elif intent == "out_of_office":
            action_taken = "ooo_detected"
            requires_approval = False
            # Schedule follow-up for later
            self.repo.update_conversation_after_message(
                conversation_id=conversation.id,
                message_from="them",
                schedule_follow_up_days=7,
            )

        else:
            # Default: generate a contextual response
            draft_response = self.responder.generate_general_response(
                influencer_name=influencer.name,
                email_content=original_message.body,
                classification=classification,
            )

        # Create pending approval if needed
        if draft_response and requires_approval:
            self.repo.create_pending_approval(
                conversation_id=conversation.id,
                draft_response=draft_response,
                response_type=intent,
                summary=f"{influencer.name}: {classification.summary}",
                their_last_message=original_message.body[:500],
                recommendation=action_taken,
                their_rate=classification.extracted_data.get("requested_rate"),
                our_counter=classification.extracted_data.get("our_counter"),
                priority="high" if intent in ["accepting_offer", "submitting_content"] else "medium",
            )

        return ProcessedEmail(
            email_id=original_message.message_id,
            conversation_id=conversation.id,
            influencer_id=influencer.id,
            classification=classification,
            draft_response=draft_response,
            requires_approval=requires_approval,
            auto_approved=auto_approved,
            action_taken=action_taken,
        )

    def _calculate_counter_offer(
        self,
        their_rate: float,
        initial_offer: Optional[float],
        current_offer: Optional[float],
    ) -> float:
        """Calculate our counter offer based on negotiation rules."""
        base = current_offer or initial_offer or their_rate * 0.7

        # Get max we can offer
        max_offer = self.pricing.get_max_offer(initial_offer or base)

        if their_rate <= base * 1.1:
            # Within 10%, accept their rate
            return their_rate
        elif their_rate <= max_offer:
            # Meet in the middle
            return round((base + their_rate) / 2, 2)
        else:
            # Offer our max
            return max_offer

    def process_follow_ups(self) -> list[ProcessedEmail]:
        """Process conversations that need follow-up."""
        logger.info("Checking for follow-ups needed...")

        conversations = self.repo.get_conversations_needing_follow_up()
        logger.info(f"Found {len(conversations)} conversations needing follow-up")

        processed = []
        for conv in conversations:
            # Get influencer
            influencer = self.repo.get_influencer_by_id(conv.influencer_id)
            if not influencer:
                continue

            # Generate follow-up
            follow_up_number = conv.follow_up_count + 1
            draft = self.responder.generate_follow_up(
                influencer_name=influencer.name,
                follow_up_number=follow_up_number,
            )

            # Create pending approval
            self.repo.create_pending_approval(
                conversation_id=conv.id,
                draft_response=draft,
                response_type=f"follow_up_{follow_up_number}",
                summary=f"Follow-up #{follow_up_number} for {influencer.name}",
                priority="low",
            )

            processed.append(
                ProcessedEmail(
                    email_id="",
                    conversation_id=conv.id,
                    influencer_id=influencer.id,
                    classification=None,
                    draft_response=draft,
                    requires_approval=True,
                    auto_approved=False,
                    action_taken=f"follow_up_{follow_up_number}_drafted",
                )
            )

        return processed
