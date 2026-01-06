"""Tests for database repository."""

import pytest
from datetime import datetime, timedelta

from src.database.repository import Repository
from src.database.models import InfluencerStatus, ConversationStatus, ApprovalStatus


@pytest.fixture
def repo():
    """Create a test repository with in-memory database."""
    return Repository("sqlite:///:memory:")


class TestInfluencerOperations:
    """Tests for influencer database operations."""

    def test_create_influencer(self, repo):
        """Test creating a new influencer."""
        influencer = repo.create_influencer(
            email="test@example.com",
            name="Test Influencer",
            platform="instagram",
            handle="testinfluencer",
            follower_count=50000,
            tier="micro",
            initial_rate=300,
        )

        assert influencer.id is not None
        assert influencer.email == "test@example.com"
        assert influencer.status == InfluencerStatus.SOURCED

    def test_get_influencer_by_email(self, repo):
        """Test finding influencer by email."""
        repo.create_influencer(email="find@example.com", name="Findable")

        found = repo.get_influencer_by_email("find@example.com")
        assert found is not None
        assert found.name == "Findable"

        not_found = repo.get_influencer_by_email("notexist@example.com")
        assert not_found is None

    def test_update_influencer_status(self, repo):
        """Test updating influencer status."""
        influencer = repo.create_influencer(email="status@example.com")

        repo.update_influencer_status(influencer.id, InfluencerStatus.CONTACTED)

        updated = repo.get_influencer_by_id(influencer.id)
        assert updated.status == InfluencerStatus.CONTACTED

    def test_get_influencers_by_status(self, repo):
        """Test filtering influencers by status."""
        repo.create_influencer(email="one@example.com")
        repo.create_influencer(email="two@example.com")

        inf3 = repo.create_influencer(email="three@example.com")
        repo.update_influencer_status(inf3.id, InfluencerStatus.NEGOTIATING)

        sourced = repo.get_influencers_by_status(InfluencerStatus.SOURCED)
        assert len(sourced) == 2

        negotiating = repo.get_influencers_by_status(InfluencerStatus.NEGOTIATING)
        assert len(negotiating) == 1


class TestConversationOperations:
    """Tests for conversation database operations."""

    def test_create_conversation(self, repo):
        """Test creating a conversation."""
        influencer = repo.create_influencer(email="conv@example.com")

        conv = repo.create_conversation(
            influencer_id=influencer.id,
            gmail_thread_id="thread123",
            subject="Test Subject",
        )

        assert conv.id is not None
        assert conv.gmail_thread_id == "thread123"
        assert conv.status == ConversationStatus.ACTIVE

    def test_get_conversation_by_thread_id(self, repo):
        """Test finding conversation by Gmail thread ID."""
        influencer = repo.create_influencer(email="thread@example.com")
        repo.create_conversation(
            influencer_id=influencer.id,
            gmail_thread_id="unique_thread",
        )

        found = repo.get_conversation_by_thread_id("unique_thread")
        assert found is not None

    def test_update_conversation_after_message(self, repo):
        """Test updating conversation after message."""
        influencer = repo.create_influencer(email="msg@example.com")
        conv = repo.create_conversation(
            influencer_id=influencer.id,
            gmail_thread_id="msg_thread",
        )

        repo.update_conversation_after_message(
            conversation_id=conv.id,
            message_from="them",
        )

        updated = repo.get_conversation_by_thread_id("msg_thread")
        assert updated.last_message_from == "them"
        assert updated.message_count == 1


class TestPendingApprovalOperations:
    """Tests for pending approval operations."""

    def test_create_pending_approval(self, repo):
        """Test creating a pending approval."""
        influencer = repo.create_influencer(email="approval@example.com")
        conv = repo.create_conversation(
            influencer_id=influencer.id,
            gmail_thread_id="approval_thread",
        )

        approval = repo.create_pending_approval(
            conversation_id=conv.id,
            draft_response="This is a draft response",
            response_type="negotiation_counter",
            summary="Counter offer for test influencer",
            their_rate=500,
            our_counter=400,
        )

        assert approval.id is not None
        assert approval.status == ApprovalStatus.PENDING

    def test_approve_response(self, repo):
        """Test approving a response."""
        influencer = repo.create_influencer(email="approve@example.com")
        conv = repo.create_conversation(
            influencer_id=influencer.id,
            gmail_thread_id="approve_thread",
        )
        approval = repo.create_pending_approval(
            conversation_id=conv.id,
            draft_response="Draft",
            response_type="test",
            summary="Test",
        )

        result = repo.approve_response(approval.id)
        assert result.status == ApprovalStatus.APPROVED

    def test_approve_with_edit(self, repo):
        """Test approving with edits."""
        influencer = repo.create_influencer(email="edit@example.com")
        conv = repo.create_conversation(
            influencer_id=influencer.id,
            gmail_thread_id="edit_thread",
        )
        approval = repo.create_pending_approval(
            conversation_id=conv.id,
            draft_response="Original draft",
            response_type="test",
            summary="Test",
        )

        result = repo.approve_response(approval.id, edited_response="Edited draft")
        assert result.status == ApprovalStatus.EDITED
        assert result.edited_response == "Edited draft"

    def test_get_pending_approvals(self, repo):
        """Test getting all pending approvals."""
        influencer = repo.create_influencer(email="pending@example.com")
        conv = repo.create_conversation(
            influencer_id=influencer.id,
            gmail_thread_id="pending_thread",
        )

        repo.create_pending_approval(
            conversation_id=conv.id,
            draft_response="Draft 1",
            response_type="test",
            summary="Test 1",
        )
        repo.create_pending_approval(
            conversation_id=conv.id,
            draft_response="Draft 2",
            response_type="test",
            summary="Test 2",
        )

        pending = repo.get_pending_approvals()
        assert len(pending) == 2
