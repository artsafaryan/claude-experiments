"""Context-aware response generation for Customuse influencer emails."""

import re
import yaml
from typing import Optional
from pathlib import Path
from dataclasses import dataclass, field

import anthropic

from ..utils.config import get_settings
from ..utils.logging import get_logger

logger = get_logger("responder")


def load_yaml_config(filename: str) -> dict:
    """Load a YAML config file."""
    config_path = Path(__file__).parent.parent.parent / "config" / filename
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f)
    return {}


def load_text_config(filename: str) -> str:
    """Load a text config file."""
    config_path = Path(__file__).parent.parent.parent / "config" / filename
    if config_path.exists():
        with open(config_path) as f:
            return f.read()
    return ""


@dataclass
class DraftResponse:
    """A draft email response ready for Slack approval."""
    body: str
    template_used: Optional[str]
    needs_input: list = field(default_factory=list)
    can_adjust: list = field(default_factory=list)
    variables_used: dict = field(default_factory=dict)


class ResponseGenerator:
    """Generates email responses using Customuse templates and Claude."""

    def __init__(self):
        self.settings = get_settings()
        self.client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)

        # Load all config files
        self.context = load_yaml_config("context.yaml")
        self.templates_config = load_yaml_config("templates.yaml")
        self.pricing_config = load_yaml_config("pricing.yaml")
        self.communication_guide = load_text_config("communication_guide.md")

        # Extract commonly used values
        self.signature = self.context.get("signature", "Best,\nPauline")
        self.company = self.context.get("company", {})
        self.manager = self.context.get("marketing_manager", {})

    def get_template(self, template_name: str) -> Optional[dict]:
        """Get a template by name."""
        return self.templates_config.get("templates", {}).get(template_name)

    # =========================================================
    # Methods called by EmailProcessor - return STRINGS
    # =========================================================

    def generate_deal_confirmation(
        self,
        influencer_name: str,
        agreed_rate: Optional[float] = None,
        promo_code: Optional[str] = None,
        preview_deadline: Optional[str] = None,
    ) -> str:
        """Generate deal confirmation with brief. Returns string for processor."""
        template = self.get_template("deal_accepted_send_brief")

        body = f"""Hi {influencer_name},
I hope you are well,

Great news! We're excited to move forward with the collaboration.

"""
        if agreed_rate:
            body += f"As discussed, the rate will be ${int(agreed_rate)}.\n\n"

        body += """For the content, please follow the brief: HERE

"""
        if promo_code:
            body += f"You have a code for your community: {promo_code}\n\n"
        else:
            body += "You have a code for your community: {{NEEDS_PROMO_CODE}}\n\n"

        if preview_deadline:
            body += f"Would you be able to send the preview by {preview_deadline}?\n\n"
        else:
            body += "Would you be able to send the preview by {{NEEDS_DEADLINE}}?\n\n"

        body += f"""{self.signature}"""

        return body

    def generate_counter_offer(
        self,
        influencer_name: str,
        their_rate: float,
        our_counter: float,
        use_performance: bool = False,
    ) -> str:
        """Generate a counter-offer response. Returns string for processor."""
        if use_performance:
            body = f"""Hi {influencer_name},
I hope you are well,

Thank you for getting back to me with your rate of ${int(their_rate)}.

Based on the current views and engagement on your channel, we could offer a performance-based deal:
- ${int(our_counter)} security deposit
- $100 per 100k views within the first week (capped at 1M views)

This way, if the video performs well, you could earn significantly more. Let me know what you think!

{self.signature}"""
        else:
            body = f"""Hi {influencer_name},
I hope you are well,

Thank you for getting back to me with your rate of ${int(their_rate)}.

Based on the current views and engagement on your channel, we could offer ${int(our_counter)} for a short-form video (30-60 seconds).

Let me know if this works for you!

{self.signature}"""

        return body

    def generate_question_response(
        self,
        influencer_name: str,
        question_type: str = "general",
        question_content: str = "",
    ) -> str:
        """Generate a response to an influencer's question. Returns string."""
        # Use Claude to generate a helpful response
        system_prompt = f"""You are Pauline, Influencer Marketing Manager at Customuse.
You're drafting an email response to an influencer who asked a question.

About Customuse: {self.company.get('product_description', 'Platform for Roblox players')}

Communication style: Friendly but professional. Start with "Hi [Name], I hope you are well,"

Question type: {question_type}

Keep the response helpful but concise. End with the signature:
{self.signature}"""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                system=system_prompt,
                messages=[{"role": "user", "content": f"Respond to this question from {influencer_name}:\n\n{question_content[:500]}"}]
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"Error generating question response: {e}")
            return f"""Hi {influencer_name},
I hope you are well,

Thank you for your question! I'll look into this and get back to you shortly.

{self.signature}"""

    def generate_content_received_response(
        self,
        influencer_name: str,
        content_type: str = "preview",
    ) -> str:
        """Generate a response acknowledging content was received. Returns string."""
        return f"""Hi {influencer_name},
I hope you are well,

Thank you for sending the {content_type}! I'll review it and get back to you shortly.

{self.signature}"""

    def generate_general_response(
        self,
        influencer_name: str,
        email_content: str,
        classification: Optional[object] = None,
    ) -> str:
        """Generate a general response for any intent. Returns string."""
        intent = classification.intent if classification else "unknown"
        summary = classification.summary if classification else "their message"

        # Use Claude to generate a contextual response
        system_prompt = f"""You are Pauline, Influencer Marketing Manager at Customuse.
You're drafting an email response to an influencer.

About Customuse: {self.company.get('product_description', 'Platform for Roblox players')}

Communication style: Friendly but professional. Start with "Hi [Name], I hope you are well,"
Keep responses concise. End with the signature:
{self.signature}

IMPORTANT: Use placeholders for things you don't know:
- {{{{NEEDS_PROMO_CODE}}}} for promo codes
- {{{{NEEDS_DEADLINE}}}} for deadlines"""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                system=system_prompt,
                messages=[{"role": "user", "content": f"Respond to this email from {influencer_name} (intent: {intent}, summary: {summary}):\n\n{email_content[:500]}"}]
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"Error generating general response: {e}")
            return f"""Hi {influencer_name},
I hope you are well,

Thank you for your message! I'll review this and get back to you shortly.

{self.signature}"""

    def generate_follow_up(
        self,
        influencer_name: str,
        follow_up_number: int = 1,
    ) -> str:
        """Generate a follow-up email. Returns string."""
        if follow_up_number == 1:
            return f"""Hi {influencer_name},
I hope you are well,

Circling back on my previous email. Please let me know if you're still interested in collaborating with Customuse!

{self.signature}"""
        else:
            return f"""Hi {influencer_name},
I hope you are well,

Just following up one more time on the collaboration opportunity. If you're no longer interested, no worries at all - just let me know!

{self.signature}"""

    # =========================================================
    # Methods used by SlackBot - return DraftResponse for rich UI
    # =========================================================

    def generate_response_draft(
        self,
        intent: str,
        influencer_name: str,
        platform: str = "YouTube",
        their_rate: Optional[float] = None,
        our_offer: Optional[float] = None,
        promo_code: Optional[str] = None,
        preview_deadline: Optional[str] = None,
        classification: Optional[object] = None,
        original_message: Optional[str] = None,
    ) -> DraftResponse:
        """Generate a response with full DraftResponse for Slack UI."""
        body = ""
        needs_input = []
        template_used = None

        # Map intent to response
        if intent == "accepting_offer":
            body = self.generate_deal_confirmation(influencer_name, our_offer, promo_code, preview_deadline)
            template_used = "deal_accepted_send_brief"
        elif intent == "negotiating_price":
            body = self.generate_counter_offer(influencer_name, their_rate or 0, our_offer or 0)
            template_used = "counter_offer_flat"
        elif intent == "asking_question":
            body = self.generate_question_response(influencer_name, "general", original_message or "")
        elif intent == "sent_preview":
            body = self.generate_content_received_response(influencer_name, "preview")
            template_used = "preview_received"
        else:
            body = self.generate_general_response(influencer_name, original_message or "", classification)

        # Check for unfilled placeholders
        if "{{NEEDS_PROMO_CODE}}" in body:
            needs_input.append({"field": "promo_code", "description": "Unique promo code", "type": "text"})
        if "{{NEEDS_DEADLINE}}" in body:
            needs_input.append({"field": "preview_deadline", "description": "Preview deadline", "type": "text"})
        if "{{NEEDS_FEEDBACK}}" in body:
            needs_input.append({"field": "feedback", "description": "Feedback on preview", "type": "text"})

        return DraftResponse(
            body=body,
            template_used=template_used,
            needs_input=needs_input,
            can_adjust=["our_offer"] if intent == "negotiating_price" else [],
            variables_used={"our_offer": our_offer, "their_rate": their_rate},
        )

    def generate_counter_offer_draft(
        self,
        influencer_name: str,
        their_rate: float,
        our_counter: float,
        use_performance: bool = False,
    ) -> DraftResponse:
        """Generate counter-offer with DraftResponse for Slack adjustment UI."""
        body = self.generate_counter_offer(influencer_name, their_rate, our_counter, use_performance)

        return DraftResponse(
            body=body,
            template_used="counter_offer_performance" if use_performance else "counter_offer_flat",
            needs_input=[],
            can_adjust=["our_offer"],
            variables_used={"our_offer": our_counter, "their_rate": their_rate},
        )

    def apply_user_inputs(self, draft: DraftResponse, inputs: dict) -> DraftResponse:
        """Apply user-provided inputs to fill remaining placeholders."""
        body = draft.body

        for field, value in inputs.items():
            placeholder_patterns = [
                f"{{{{{field}}}}}",
                f"{{{{NEEDS_{field.upper()}}}}}",
                f"{{{{needs_{field}}}}}",
            ]

            for pattern in placeholder_patterns:
                body = body.replace(pattern, str(value))

        # Update needs_input to remove filled fields
        remaining_needs = [ni for ni in draft.needs_input if ni['field'] not in inputs]

        return DraftResponse(
            body=body,
            template_used=draft.template_used,
            needs_input=remaining_needs,
            can_adjust=draft.can_adjust,
            variables_used={**draft.variables_used, **inputs},
        )
