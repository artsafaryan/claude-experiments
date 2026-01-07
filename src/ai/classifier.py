"""Email classification using Claude - Customuse-specific intents."""

import json
import yaml
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

import anthropic

from ..utils.config import get_settings, get_rules
from ..utils.logging import get_logger

logger = get_logger("classifier")


def load_context() -> dict:
    """Load company context from config."""
    context_path = Path(__file__).parent.parent.parent / "config" / "context.yaml"
    if context_path.exists():
        with open(context_path) as f:
            return yaml.safe_load(f)
    return {}


def load_communication_guide() -> str:
    """Load communication guide from config."""
    guide_path = Path(__file__).parent.parent.parent / "config" / "communication_guide.md"
    if guide_path.exists():
        with open(guide_path) as f:
            return f.read()
    return ""


@dataclass
class ClassificationResult:
    """Result of email classification."""

    intent: str
    confidence: float
    summary: str
    extracted_data: dict = field(default_factory=dict)
    requires_escalation: bool = False
    escalation_reason: Optional[str] = None
    suggested_template: Optional[str] = None
    missing_info: list = field(default_factory=list)


class EmailClassifier:
    """Classifies incoming influencer emails for Customuse."""

    def __init__(self):
        self.settings = get_settings()
        self.rules = get_rules()
        self.client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        self.context = load_context()
        self.communication_guide = load_communication_guide()

    def _build_system_prompt(self) -> str:
        """Build system prompt with full Customuse context."""
        return f"""You are an AI assistant helping Pauline (Influencer Marketing Manager at Customuse) manage influencer email conversations.

## About Customuse
{self.context.get('company', {}).get('product_description', 'A platform for Roblox players to create 3D accessories')}
Website: {self.context.get('company', {}).get('website', 'https://customuse.com')}

## Your Role
Classify incoming emails from influencers to determine:
1. What stage of conversation this is
2. What the influencer is communicating
3. What response template to use
4. What information we still need from them

## Intent Categories (map to conversation stages)

### Stage 1 - Initial Response
- **interested**: Influencer responded positively, wants to proceed (but may not have given details yet)
- **sent_insights_no_rate**: They sent their analytics/insights but didn't mention their rate
- **sent_rate_no_insights**: They mentioned their rate but didn't send insights/analytics
- **sent_both**: They provided both insights AND rate in one message

### Stage 2 - Negotiation
- **negotiating_price**: They're counter-offering or discussing the rate
- **accepting_offer**: They agreed to our proposed rate
- **declining_offer**: They said no or the rate is too low for them
- **asking_question**: They have questions about the campaign, format, payment, etc.

### Stage 3 - Production
- **needs_pro_access**: They're asking for PRO access to film content
- **sent_username**: They sent their Customuse username (for PRO access)
- **sent_payment_details**: They provided their payment information (name, address, PayPal)

### Stage 4 - Content Review
- **sent_preview**: They sent content/preview for review
- **content_published**: They're saying the video is live / sending the link

### Stage 5 - Post-Publish
- **asking_about_payment**: Questions about when/how they'll be paid
- **asking_about_bonus**: Questions about performance bonus

### Other
- **delayed**: They can't do it right now, need to postpone
- **follow_up_response**: Responding to our follow-up
- **re_engagement**: Responding to a new collab offer (we worked together before)
- **out_of_office**: Auto-reply
- **unrelated**: Not about influencer collaboration

## Data to Extract
- **their_rate**: Any rate/price they mention (as integer, USD)
- **their_platform**: TikTok, YouTube, Instagram, etc.
- **their_username**: Customuse username if mentioned
- **insights_shared**: true/false - did they share analytics/insights
- **payment_details_shared**: true/false - did they share payment info
- **content_link**: URL to preview or published content
- **availability**: When they can do the content
- **questions**: List of questions they're asking

## Escalation Triggers
Flag requires_escalation=true if email mentions:
- "agency" or "manager"
- "contract" or "legal"
- "exclusive" or "exclusivity"
- "long-term" or "ongoing"
- Any rate above $1000
- Long-form video requests
- Usage rights or licensing
- Competitor brands

Respond in JSON format only."""

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
                direction = "Pauline (us)" if msg["direction"] == "outbound" else "Influencer"
                body_preview = msg['body'][:500] if msg['body'] else ""
                history_context += f"\n[{direction}]:\n{body_preview}\n"

        # Build the prompt
        user_prompt = f"""Classify this email from an influencer:

Subject: {email_subject}

Body:
{email_body}
{history_context}

Respond with JSON:
{{
    "intent": "category_name",
    "confidence": 0.0-1.0,
    "summary": "Brief one-sentence summary",
    "extracted_data": {{
        "their_rate": null or integer,
        "their_platform": null or string,
        "their_username": null or string,
        "insights_shared": true/false,
        "payment_details_shared": true/false,
        "content_link": null or string,
        "availability": null or string,
        "questions": []
    }},
    "requires_escalation": true/false,
    "escalation_reason": null or "reason",
    "suggested_template": "template_name or null",
    "missing_info": ["list of info we still need"]
}}"""

        try:
            response = self.client.messages.create(
                model="claude-3-5-haiku-20241022",  # Haiku for cost-effective classification
                max_tokens=800,
                messages=[
                    {"role": "user", "content": user_prompt}
                ],
                system=self._build_system_prompt(),
            )

            # Parse response
            response_text = response.content[0].text

            # Handle potential markdown code blocks
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]

            result = json.loads(response_text.strip())

            # Check for escalation triggers (belt and suspenders)
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
                suggested_template=result.get("suggested_template"),
                missing_info=result.get("missing_info", []),
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude response: {e}")
            logger.error(f"Response was: {response_text[:500] if 'response_text' in dir() else 'N/A'}")
            return ClassificationResult(
                intent="unrelated",
                confidence=0.5,
                summary="Failed to classify email",
                requires_escalation=True,
                escalation_reason="Classification failed - needs manual review",
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
        escalation_keywords = [
            "agency", "manager", "contract", "legal",
            "exclusive", "exclusivity", "long-term", "ongoing partnership",
            "long-form", "usage rights", "licensing"
        ]

        for keyword in escalation_keywords:
            if keyword in email_lower:
                return True, f"Contains escalation keyword: {keyword}"

        # Check rate threshold
        extracted_rate = classification.get("extracted_data", {}).get("their_rate")
        if extracted_rate and extracted_rate > 1000:
            return True, f"Rate ${extracted_rate} exceeds $1000 threshold"

        return False, None

    def get_suggested_template(self, intent: str, extracted_data: dict) -> Optional[str]:
        """Map intent to suggested response template."""
        # Template mapping based on intent and what data we have
        template_map = {
            "interested": "request_insights_and_rate",
            "sent_insights_no_rate": "request_rate_only",
            "sent_rate_no_insights": "request_insights_only",
            "sent_both": "counter_offer_flat",  # Ready to make offer
            "negotiating_price": "counter_offer_flat",  # Or counter_offer_performance
            "accepting_offer": "deal_accepted_send_brief",
            "declining_offer": None,  # No response needed
            "needs_pro_access": "request_username",
            "sent_username": "grant_pro_access",
            "sent_payment_details": "confirm_payment_sent",
            "sent_preview": "preview_approved",  # Or preview_needs_changes
            "content_published": "video_live_confirmation",
            "asking_question": None,  # Needs custom response
            "delayed": "acknowledge_delay",
            "re_engagement": "re_engagement_follow_up",
        }

        return template_map.get(intent)
