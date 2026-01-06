"""Data access layer for database operations."""

from datetime import datetime, timedelta
from typing import Optional
from contextlib import contextmanager

from sqlalchemy import create_engine, and_, or_
from sqlalchemy.orm import sessionmaker, Session

from .models import (
    Base,
    Influencer,
    Conversation,
    Email,
    PendingApproval,
    NegotiationEvent,
    InfluencerStatus,
    ConversationStatus,
    ApprovalStatus,
)
from ..utils.config import get_settings


class Repository:
    """Repository for database operations."""

    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url or get_settings().database_url
        self.engine = create_engine(self.database_url)
        # expire_on_commit=False allows objects to be used after session closes
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

        # Create tables if they don't exist
        Base.metadata.create_all(self.engine)

    @contextmanager
    def get_session(self):
        """Context manager for database sessions."""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ==================== Influencer Operations ====================

    def create_influencer(
        self,
        email: str,
        name: Optional[str] = None,
        platform: Optional[str] = None,
        handle: Optional[str] = None,
        follower_count: Optional[int] = None,
        tier: Optional[str] = None,
        initial_rate: Optional[float] = None,
        content_type: Optional[str] = None,
    ) -> Influencer:
        """Create a new influencer record."""
        with self.get_session() as session:
            influencer = Influencer(
                email=email,
                name=name,
                platform=platform,
                handle=handle,
                follower_count=follower_count,
                tier=tier,
                initial_rate_offered=initial_rate,
                current_offer=initial_rate,
                content_type=content_type,
            )
            session.add(influencer)
            session.flush()
            session.refresh(influencer)
            session.expunge(influencer)
            return influencer

    def get_influencer_by_email(self, email: str) -> Optional[Influencer]:
        """Find an influencer by email address."""
        with self.get_session() as session:
            influencer = session.query(Influencer).filter(Influencer.email == email).first()
            if influencer:
                session.expunge(influencer)
            return influencer

    def get_influencer_by_id(self, influencer_id: str) -> Optional[Influencer]:
        """Find an influencer by ID."""
        with self.get_session() as session:
            influencer = session.query(Influencer).filter(Influencer.id == influencer_id).first()
            if influencer:
                session.expunge(influencer)
            return influencer

    def update_influencer_status(
        self, influencer_id: str, status: InfluencerStatus
    ) -> None:
        """Update an influencer's status."""
        with self.get_session() as session:
            influencer = session.query(Influencer).filter(Influencer.id == influencer_id).first()
            if influencer:
                influencer.status = status
                influencer.updated_at = datetime.utcnow()

    def get_influencers_by_status(self, status: InfluencerStatus) -> list[Influencer]:
        """Get all influencers with a specific status."""
        with self.get_session() as session:
            influencers = session.query(Influencer).filter(Influencer.status == status).all()
            for inf in influencers:
                session.expunge(inf)
            return influencers

    # ==================== Conversation Operations ====================

    def create_conversation(
        self,
        influencer_id: str,
        gmail_thread_id: str,
        subject: Optional[str] = None,
    ) -> Conversation:
        """Create a new conversation."""
        with self.get_session() as session:
            conversation = Conversation(
                influencer_id=influencer_id,
                gmail_thread_id=gmail_thread_id,
                subject=subject,
            )
            session.add(conversation)
            session.flush()
            session.refresh(conversation)
            session.expunge(conversation)
            return conversation

    def get_conversation_by_thread_id(self, thread_id: str) -> Optional[Conversation]:
        """Find a conversation by Gmail thread ID."""
        with self.get_session() as session:
            conv = (
                session.query(Conversation)
                .filter(Conversation.gmail_thread_id == thread_id)
                .first()
            )
            if conv:
                session.expunge(conv)
            return conv

    def get_active_conversations(self) -> list[Conversation]:
        """Get all active conversations."""
        with self.get_session() as session:
            convs = (
                session.query(Conversation)
                .filter(
                    Conversation.status.in_([
                        ConversationStatus.ACTIVE,
                        ConversationStatus.PENDING_RESPONSE,
                    ])
                )
                .all()
            )
            for conv in convs:
                session.expunge(conv)
            return convs

    def get_conversations_needing_follow_up(self) -> list[Conversation]:
        """Get conversations that need follow-up."""
        with self.get_session() as session:
            now = datetime.utcnow()
            convs = (
                session.query(Conversation)
                .filter(
                    and_(
                        Conversation.status == ConversationStatus.PENDING_RESPONSE,
                        Conversation.next_follow_up_at <= now,
                        Conversation.follow_up_count < 2,  # Max 2 follow-ups
                    )
                )
                .all()
            )
            for conv in convs:
                session.expunge(conv)
            return convs

    def update_conversation_after_message(
        self,
        conversation_id: str,
        message_from: str,
        schedule_follow_up_days: Optional[int] = None,
    ) -> None:
        """Update conversation after a message is sent/received."""
        with self.get_session() as session:
            conversation = (
                session.query(Conversation)
                .filter(Conversation.id == conversation_id)
                .first()
            )
            if conversation:
                conversation.last_message_at = datetime.utcnow()
                conversation.last_message_from = message_from
                conversation.message_count += 1

                if message_from == "us" and schedule_follow_up_days:
                    conversation.next_follow_up_at = datetime.utcnow() + timedelta(
                        days=schedule_follow_up_days
                    )
                elif message_from == "them":
                    # They replied, reset follow-up
                    conversation.next_follow_up_at = None
                    conversation.follow_up_count = 0

    # ==================== Email Operations ====================

    def create_email(
        self,
        conversation_id: str,
        gmail_message_id: str,
        direction: str,
        from_email: str,
        to_email: str,
        subject: str,
        body: str,
        body_html: Optional[str] = None,
        sent_at: Optional[datetime] = None,
    ) -> Email:
        """Create a new email record."""
        with self.get_session() as session:
            email = Email(
                conversation_id=conversation_id,
                gmail_message_id=gmail_message_id,
                direction=direction,
                from_email=from_email,
                to_email=to_email,
                subject=subject,
                body=body,
                body_html=body_html,
                sent_at=sent_at or datetime.utcnow(),
                received_at=datetime.utcnow() if direction == "inbound" else None,
            )
            session.add(email)
            session.flush()
            session.refresh(email)
            session.expunge(email)
            return email

    def get_email_by_message_id(self, message_id: str) -> Optional[Email]:
        """Find an email by Gmail message ID."""
        with self.get_session() as session:
            email = (
                session.query(Email)
                .filter(Email.gmail_message_id == message_id)
                .first()
            )
            if email:
                session.expunge(email)
            return email

    def get_conversation_emails(self, conversation_id: str) -> list[Email]:
        """Get all emails in a conversation, ordered by date."""
        with self.get_session() as session:
            emails = (
                session.query(Email)
                .filter(Email.conversation_id == conversation_id)
                .order_by(Email.sent_at)
                .all()
            )
            for email in emails:
                session.expunge(email)
            return emails

    def update_email_classification(
        self,
        email_id: str,
        intent: str,
        confidence: float,
        extracted_data: Optional[dict] = None,
    ) -> None:
        """Update email with classification results."""
        with self.get_session() as session:
            email = session.query(Email).filter(Email.id == email_id).first()
            if email:
                email.intent_classification = intent
                email.confidence_score = confidence
                email.extracted_data = extracted_data
                email.is_processed = True
                email.processed_at = datetime.utcnow()

    # ==================== Pending Approval Operations ====================

    def create_pending_approval(
        self,
        conversation_id: str,
        draft_response: str,
        response_type: str,
        summary: str,
        their_last_message: Optional[str] = None,
        recommendation: Optional[str] = None,
        their_rate: Optional[float] = None,
        our_counter: Optional[float] = None,
        priority: str = "medium",
        draft_subject: Optional[str] = None,
    ) -> PendingApproval:
        """Create a new pending approval."""
        with self.get_session() as session:
            approval = PendingApproval(
                conversation_id=conversation_id,
                draft_response=draft_response,
                draft_subject=draft_subject,
                response_type=response_type,
                summary=summary,
                their_last_message=their_last_message,
                recommendation=recommendation,
                their_rate=their_rate,
                our_counter=our_counter,
                priority=priority,
            )
            session.add(approval)
            session.flush()
            session.refresh(approval)

            # Update conversation status
            conversation = (
                session.query(Conversation)
                .filter(Conversation.id == conversation_id)
                .first()
            )
            if conversation:
                conversation.status = ConversationStatus.PENDING_APPROVAL

            session.expunge(approval)
            return approval

    def get_pending_approvals(self) -> list[PendingApproval]:
        """Get all pending approvals."""
        with self.get_session() as session:
            approvals = (
                session.query(PendingApproval)
                .filter(PendingApproval.status == ApprovalStatus.PENDING)
                .order_by(PendingApproval.created_at)
                .all()
            )
            for approval in approvals:
                session.expunge(approval)
            return approvals

    def approve_response(
        self, approval_id: str, edited_response: Optional[str] = None
    ) -> PendingApproval:
        """Approve a pending response."""
        with self.get_session() as session:
            approval = (
                session.query(PendingApproval)
                .filter(PendingApproval.id == approval_id)
                .first()
            )
            if approval:
                if edited_response:
                    approval.status = ApprovalStatus.EDITED
                    approval.edited_response = edited_response
                else:
                    approval.status = ApprovalStatus.APPROVED
                approval.reviewed_at = datetime.utcnow()
                session.expunge(approval)
            return approval

    def reject_response(self, approval_id: str) -> None:
        """Reject a pending response."""
        with self.get_session() as session:
            approval = (
                session.query(PendingApproval)
                .filter(PendingApproval.id == approval_id)
                .first()
            )
            if approval:
                approval.status = ApprovalStatus.REJECTED
                approval.reviewed_at = datetime.utcnow()

    def mark_approval_sent(self, approval_id: str) -> None:
        """Mark an approved response as sent."""
        with self.get_session() as session:
            approval = (
                session.query(PendingApproval)
                .filter(PendingApproval.id == approval_id)
                .first()
            )
            if approval:
                approval.sent_at = datetime.utcnow()

    # ==================== Negotiation Event Operations ====================

    def record_negotiation_event(
        self,
        conversation_id: str,
        event_type: str,
        our_amount: Optional[float] = None,
        their_amount: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> NegotiationEvent:
        """Record a negotiation event."""
        with self.get_session() as session:
            event = NegotiationEvent(
                conversation_id=conversation_id,
                event_type=event_type,
                our_amount=our_amount,
                their_amount=their_amount,
                notes=notes,
            )
            session.add(event)
            session.flush()
            session.refresh(event)
            session.expunge(event)
            return event

    def get_negotiation_history(self, conversation_id: str) -> list[NegotiationEvent]:
        """Get negotiation history for a conversation."""
        with self.get_session() as session:
            events = (
                session.query(NegotiationEvent)
                .filter(NegotiationEvent.conversation_id == conversation_id)
                .order_by(NegotiationEvent.created_at)
                .all()
            )
            for event in events:
                session.expunge(event)
            return events


# Singleton instance
_repository: Optional[Repository] = None


def get_repository() -> Repository:
    """Get or create the repository singleton."""
    global _repository
    if _repository is None:
        _repository = Repository()
    return _repository
