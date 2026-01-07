"""SQLAlchemy database models."""

import enum
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Text,
    DateTime,
    ForeignKey,
    Enum,
    Boolean,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, Session
from sqlalchemy.dialects.sqlite import JSON

Base = declarative_base()


class InfluencerStatus(enum.Enum):
    """Status of an influencer in the pipeline."""
    SOURCED = "sourced"
    CONTACTED = "contacted"
    NEGOTIATING = "negotiating"
    AGREED = "agreed"
    DECLINED = "declined"
    STALE = "stale"
    CONTENT_PENDING = "content_pending"
    CONTENT_RECEIVED = "content_received"
    COMPLETED = "completed"


class ConversationStatus(enum.Enum):
    """Status of an email conversation."""
    ACTIVE = "active"
    PENDING_APPROVAL = "pending_approval"
    PENDING_RESPONSE = "pending_response"
    COMPLETED = "completed"
    STALE = "stale"


class ApprovalStatus(enum.Enum):
    """Status of a pending approval."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"
    AUTO_APPROVED = "auto_approved"


class Influencer(Base):
    """Influencer contact and status tracking."""

    __tablename__ = "influencers"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255))
    platform = Column(String(50))  # instagram, tiktok, youtube
    handle = Column(String(255))
    follower_count = Column(Integer)
    tier = Column(String(20))  # nano, micro, mid, macro, mega

    status = Column(
        Enum(InfluencerStatus), default=InfluencerStatus.SOURCED, index=True
    )

    # Pricing
    initial_rate_offered = Column(Float)
    current_offer = Column(Float)
    their_asking_rate = Column(Float)
    agreed_rate = Column(Float)
    content_type = Column(String(50))

    # Metadata
    notes = Column(Text)
    tags = Column(JSON)  # List of tags for categorization

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_contacted_at = Column(DateTime)
    deal_closed_at = Column(DateTime)

    # Relationships
    conversations = relationship("Conversation", back_populates="influencer")

    def __repr__(self):
        return f"<Influencer {self.name} ({self.email})>"


class Conversation(Base):
    """Email thread/conversation tracking."""

    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    influencer_id = Column(String(36), ForeignKey("influencers.id"), nullable=False)

    # Gmail tracking
    gmail_thread_id = Column(String(255), unique=True, index=True)
    subject = Column(String(500))

    # Status
    status = Column(
        Enum(ConversationStatus), default=ConversationStatus.ACTIVE, index=True
    )

    # Tracking
    last_message_at = Column(DateTime)
    last_message_from = Column(String(10))  # 'us' or 'them'
    message_count = Column(Integer, default=0)

    # Follow-up tracking
    next_follow_up_at = Column(DateTime)
    follow_up_count = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    influencer = relationship("Influencer", back_populates="conversations")
    emails = relationship("Email", back_populates="conversation")
    pending_approvals = relationship("PendingApproval", back_populates="conversation")
    negotiation_events = relationship("NegotiationEvent", back_populates="conversation")

    def __repr__(self):
        return f"<Conversation {self.gmail_thread_id}>"


class Email(Base):
    """Individual email message tracking."""

    __tablename__ = "emails"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    conversation_id = Column(String(36), ForeignKey("conversations.id"), nullable=False)

    # Gmail tracking
    gmail_message_id = Column(String(255), unique=True, index=True)

    # Email content
    direction = Column(String(10), nullable=False)  # 'inbound' or 'outbound'
    from_email = Column(String(255))
    to_email = Column(String(255))
    subject = Column(String(500))
    body = Column(Text)
    body_html = Column(Text)

    # Classification (set by Claude)
    intent_classification = Column(String(100))
    confidence_score = Column(Float)
    extracted_data = Column(JSON)  # Structured data extracted from email

    # Status
    is_processed = Column(Boolean, default=False)
    is_auto_reply = Column(Boolean, default=False)

    # Timestamps
    sent_at = Column(DateTime)
    received_at = Column(DateTime)
    processed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    conversation = relationship("Conversation", back_populates="emails")

    def __repr__(self):
        return f"<Email {self.direction} - {self.gmail_message_id}>"


class PendingApproval(Base):
    """Queue of responses awaiting human approval."""

    __tablename__ = "pending_approvals"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    conversation_id = Column(String(36), ForeignKey("conversations.id"), nullable=False)

    # The drafted response
    draft_subject = Column(String(500))
    draft_response = Column(Text, nullable=False)
    response_type = Column(String(100))  # negotiation_counter, follow_up, etc.

    # Context for reviewer
    summary = Column(Text)  # Brief summary of the situation
    their_last_message = Column(Text)  # What they said
    recommendation = Column(String(100))  # Claude's recommendation

    # Pricing context
    their_rate = Column(Float)
    our_counter = Column(Float)

    # Status
    status = Column(Enum(ApprovalStatus), default=ApprovalStatus.PENDING, index=True)
    priority = Column(String(20), default="medium")  # high, medium, low

    # Slack tracking
    slack_message_ts = Column(String(50))
    slack_channel_id = Column(String(50))

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime)
    sent_at = Column(DateTime)

    # Edited response (if reviewer made changes)
    edited_response = Column(Text)

    # Extra data for UI (JSON) - stores needs_input, can_adjust, etc.
    extra_data = Column(Text)

    # Relationships
    conversation = relationship("Conversation", back_populates="pending_approvals")

    def __repr__(self):
        return f"<PendingApproval {self.id} - {self.status.value}>"


class NegotiationEvent(Base):
    """Track negotiation history."""

    __tablename__ = "negotiation_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    conversation_id = Column(String(36), ForeignKey("conversations.id"), nullable=False)

    # Event details
    event_type = Column(String(50), nullable=False)  # offer, counter, accept, reject
    our_amount = Column(Float)
    their_amount = Column(Float)
    notes = Column(Text)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    conversation = relationship("Conversation", back_populates="negotiation_events")

    def __repr__(self):
        return f"<NegotiationEvent {self.event_type}>"


def init_db(database_url: str) -> None:
    """Initialize the database and create all tables."""
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
