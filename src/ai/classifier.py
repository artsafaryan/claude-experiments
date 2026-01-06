"""Email classification using Claude."""

import json
from dataclasses import dataclass, field
from typing import Optional

import anthropic

from ..utils.config import get_settings, get_rules
from ..utils.logging import get_logger

logger = get_logger("classifier")


@dataclass
class ClassificationResult:
    """Result of email classification."""

    intent: str
    confidence: float
    summary: str
    extracted_data: dict = field(default_factory=dict)
    requires_escalation: bool = False
    escalation_reason: Optional[str] = None


class EmailClassifier:
    """Classifies incoming emails using Claude."""

    SYSTEM_PROMPT = """You are an AI assistant that classifies influencer marketing emails.
Your job is to analyze incoming emails from influencers and classify their intent.

Available intent categories:
- interested: Positive response, wants to learn more or proceed
- negotiating_price: Counter-offering or discussing/negotiating the rate
- asking_question: Has questions about the campaign, timeline, format, etc.
- accepting_offer: Explicitly agrees to the deal/terms
- declining_offer: Not interested or explicitly declines
- submitting_content: Sending content for review
- requesting_info: Wants more details before deciding
- out_of_office: Auto-reply or out of office message
- unrelated: Not relevant to the campaign

Also extract any relevant data:
- requested_rate: If they mention a specific rate they want (as a number)
- question_type: Type of question (timeline, format, payment, usage_rights, general)
- sentiment: overall tone (positive, neutral, negative)

Respond in JSON format:
{
    "intent": "category_name",
    "confidence": 0.0-1.0,
    "summary": "Brief one-sentence summary of the email",
    "extracted_data": {
        "requested_rate": null or number,
        "question_type": null or string,
        "sentiment": "positive/neutral/negative"
    },
    "requires_escalation": true/false,
    "escalation_reason": null or "reason"
}"""

    def __init__(self):
        self.settings = get_settings()
        self.rules = get_rules()
        self.client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)

    def classify(
        self,
        email_body: str,
        email_subject: str,
        conversation_history: Optional[list[dict]] = None,
    ) -> ClassificationResult:
        """Classify an email and extract relevant information."""
        # Build context from conversation history
        history_context = ""
        if conversation_history:
            history_context = "\n\nPrevious messages in this conversation:\n"
            for msg in conversation_history[-5:]:  # Last 5 messages
                direction = "Us" if msg["direction"] == "outbound" else "Them"
                history_context += f"[{direction}]: {msg['body'][:300]}...\n"

        # Build the prompt
        user_prompt = f"""Classify this email:

Subject: {email_subject}

Body:
{email_body}
{history_context}

Respond with JSON only."""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[
                    {"role": "user", "content": user_prompt}
                ],
                system=self.SYSTEM_PROMPT,
            )

            # Parse response
            response_text = response.content[0].text
            result = json.loads(response_text)

            # Check for escalation triggers
            requires_escalation, escalation_reason = self._check_escalation_triggers(
                email_body, result
            )

            return ClassificationResult(
                intent=result["intent"],
                confidence=result["confidence"],
                summary=result["summary"],
                extracted_data=result.get("extracted_data", {}),
                requires_escalation=requires_escalation or result.get("requires_escalation", False),
                escalation_reason=escalation_reason or result.get("escalation_reason"),
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response: {e}")
            return ClassificationResult(
                intent="unrelated",
                confidence=0.5,
                summary="Failed to classify email",
                requires_escalation=True,
                escalation_reason="Classification failed",
            )
        except Exception as e:
            logger.error(f"Classification error: {e}")
            return ClassificationResult(
                intent="unrelated",
                confidence=0.0,
                summary="Error during classification",
                requires_escalation=True,
                escalation_reason=str(e),
            )

    def _check_escalation_triggers(
        self, email_body: str, classification: dict
    ) -> tuple[bool, Optional[str]]:
        """Check if email contains escalation triggers from rules."""
        email_lower = email_body.lower()

        # Check keyword triggers
        keywords = self.rules.get("escalation_triggers", {}).get("keywords", [])
        for keyword in keywords:
            if keyword.lower() in email_lower:
                return True, f"Contains keyword: {keyword}"

        # Check rate threshold
        extracted_rate = classification.get("extracted_data", {}).get("requested_rate")
        if extracted_rate:
            escalate_over = self.rules.get("negotiation", {}).get("limits", {}).get(
                "always_escalate_over", 5000
            )
            if extracted_rate > escalate_over:
                return True, f"Rate ${extracted_rate} exceeds escalation threshold"

        return False, None
