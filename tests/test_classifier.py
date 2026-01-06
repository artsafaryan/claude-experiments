"""Tests for email classification."""

import pytest
from unittest.mock import Mock, patch

from src.ai.classifier import EmailClassifier, ClassificationResult


class TestEmailClassifier:
    """Tests for EmailClassifier."""

    def test_classification_result_dataclass(self):
        """Test ClassificationResult dataclass."""
        result = ClassificationResult(
            intent="negotiating_price",
            confidence=0.95,
            summary="Influencer wants to negotiate the rate",
            extracted_data={"requested_rate": 500},
            requires_escalation=False,
        )

        assert result.intent == "negotiating_price"
        assert result.confidence == 0.95
        assert result.extracted_data["requested_rate"] == 500
        assert not result.requires_escalation

    @patch("src.ai.classifier.anthropic.Anthropic")
    def test_classify_negotiation(self, mock_anthropic):
        """Test classification of price negotiation email."""
        # Mock Claude response
        mock_response = Mock()
        mock_response.content = [Mock(text='''{
            "intent": "negotiating_price",
            "confidence": 0.92,
            "summary": "Influencer counter-offering at $500",
            "extracted_data": {"requested_rate": 500, "sentiment": "positive"},
            "requires_escalation": false
        }''')]

        mock_client = Mock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client

        classifier = EmailClassifier()
        result = classifier.classify(
            email_body="Thanks for reaching out! I'd love to work with you, but my rate is $500 for this type of content.",
            email_subject="Re: Collaboration Opportunity",
        )

        assert result.intent == "negotiating_price"
        assert result.extracted_data.get("requested_rate") == 500

    @patch("src.ai.classifier.anthropic.Anthropic")
    def test_classify_acceptance(self, mock_anthropic):
        """Test classification of acceptance email."""
        mock_response = Mock()
        mock_response.content = [Mock(text='''{
            "intent": "accepting_offer",
            "confidence": 0.98,
            "summary": "Influencer accepts the offer",
            "extracted_data": {"sentiment": "positive"},
            "requires_escalation": false
        }''')]

        mock_client = Mock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client

        classifier = EmailClassifier()
        result = classifier.classify(
            email_body="That sounds great! I'm happy to proceed with your offer.",
            email_subject="Re: Collaboration",
        )

        assert result.intent == "accepting_offer"
        assert result.confidence >= 0.9

    def test_escalation_trigger_keywords(self):
        """Test that certain keywords trigger escalation."""
        classifier = EmailClassifier()

        # Test with keyword that should trigger escalation
        requires_escalation, reason = classifier._check_escalation_triggers(
            "I need to check with my agency before proceeding",
            {"intent": "interested", "extracted_data": {}},
        )

        assert requires_escalation
        assert "agency" in reason.lower()

    def test_escalation_trigger_high_rate(self):
        """Test that high rates trigger escalation."""
        classifier = EmailClassifier()

        requires_escalation, reason = classifier._check_escalation_triggers(
            "My rate is $6000 for this content",
            {"intent": "negotiating_price", "extracted_data": {"requested_rate": 6000}},
        )

        assert requires_escalation
        assert "threshold" in reason.lower()
