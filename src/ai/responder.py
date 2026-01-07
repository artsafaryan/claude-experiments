"""Context-aware response generation for Customuse influencer emails."""

import re
import yaml
from typing import Optional
from pathlib import Path
from dataclasses import dataclass, field

import anthropic

from ..utils.config import get_settings
from ..utils.logging import get_logger
from .classifier import ClassificationResult

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
    needs_input: list = field(default_factory=list)  # Things Pauline needs to provide
    can_adjust: list = field(default_factory=list)   # Things that can be adjusted
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

    def generate_response(
        self,
        intent: str,
        influencer_name: str,
        platform: str = "YouTube",
        their_rate: Optional[float] = None,
        our_offer: Optional[float] = None,
        promo_code: Optional[str] = None,
        preview_deadline: Optional[str] = None,
        classification: Optional[ClassificationResult] = None,
        conversation_history: Optional[list[dict]] = None,
        original_message: Optional[str] = None,
    ) -> DraftResponse:
        """Generate a response based on intent and context."""

        # Map intent to template
        template_name = self._get_template_for_intent(intent, classification)

        if template_name:
            template = self.get_template(template_name)
            if template:
                return self._fill_template(
                    template_name=template_name,
                    template=template,
                    influencer_name=influencer_name,
                    platform=platform,
                    their_rate=their_rate,
                    our_offer=our_offer,
                    promo_code=promo_code,
                    preview_deadline=preview_deadline,
                )

        # Fall back to Claude-generated response
        return self._generate_custom_response(
            intent=intent,
            influencer_name=influencer_name,
            classification=classification,
            original_message=original_message,
            conversation_history=conversation_history,
        )

    def _get_template_for_intent(
        self,
        intent: str,
        classification: Optional[ClassificationResult] = None
    ) -> Optional[str]:
        """Map intent to the best template."""
        # Check if classifier already suggested a template
        if classification and classification.suggested_template:
            return classification.suggested_template

        # Intent to template mapping
        intent_mapping = self.templates_config.get("intent_mapping", {})
        templates_for_intent = intent_mapping.get(intent, [])

        if templates_for_intent:
            # Return first template (could be smarter about selection)
            return templates_for_intent[0] if isinstance(templates_for_intent, list) else templates_for_intent

        # Direct mapping fallback
        direct_map = {
            "interested": "request_insights_and_rate",
            "sent_insights_no_rate": "request_rate_only",
            "sent_rate_no_insights": "request_insights_only",
            "sent_both": "counter_offer_flat",
            "negotiating_price": "counter_offer_flat",
            "accepting_offer": "deal_accepted_send_brief",
            "needs_pro_access": "request_username",
            "sent_username": "grant_pro_access",
            "sent_payment_details": "confirm_payment_sent",
            "sent_preview": "preview_approved",
            "content_published": "video_live_confirmation",
            "delayed": "acknowledge_delay",
            "re_engagement": "re_engagement_new_collab",
        }

        return direct_map.get(intent)

    def _fill_template(
        self,
        template_name: str,
        template: dict,
        influencer_name: str,
        platform: str = "YouTube",
        their_rate: Optional[float] = None,
        our_offer: Optional[float] = None,
        promo_code: Optional[str] = None,
        preview_deadline: Optional[str] = None,
    ) -> DraftResponse:
        """Fill in a template with variables."""
        body = template.get("body", "")

        # Track what was filled and what needs input
        needs_input = []
        can_adjust = []
        variables_used = {}

        # Replace standard variables
        replacements = {
            "{{influencer_name}}": influencer_name,
            "{{platform}}": platform,
            "{{signature}}": self.signature,
        }

        # Rate-related variables
        if our_offer is not None:
            replacements["{{our_offer}}"] = str(int(our_offer))
            variables_used["our_offer"] = our_offer
            can_adjust.append("our_offer")
        elif "{{our_offer}}" in body:
            # Need to calculate or ask for offer
            needs_input.append({
                "field": "our_offer",
                "description": "Our offer amount (USD)",
                "type": "number"
            })

        if their_rate is not None:
            replacements["{{their_rate}}"] = str(int(their_rate))
            variables_used["their_rate"] = their_rate

        if promo_code:
            replacements["{{promo_code}}"] = promo_code
            replacements["{{NEEDS_PROMO_CODE}}"] = promo_code
            variables_used["promo_code"] = promo_code
        elif "{{NEEDS_PROMO_CODE}}" in body or "{{promo_code}}" in body:
            needs_input.append({
                "field": "promo_code",
                "description": "Unique promo code for this influencer",
                "type": "text"
            })

        if preview_deadline:
            replacements["{{preview_deadline}}"] = preview_deadline
            replacements["{{NEEDS_DEADLINE}}"] = preview_deadline
            variables_used["preview_deadline"] = preview_deadline
        elif "{{NEEDS_DEADLINE}}" in body or "{{preview_deadline}}" in body:
            needs_input.append({
                "field": "preview_deadline",
                "description": "Deadline for content preview (e.g., 'Friday EOD')",
                "type": "text"
            })

        if "{{NEEDS_FEEDBACK}}" in body:
            needs_input.append({
                "field": "feedback",
                "description": "Specific feedback on the preview",
                "type": "text"
            })

        # Apply replacements
        for placeholder, value in replacements.items():
            body = body.replace(placeholder, value)

        # Check for any remaining unfilled placeholders
        remaining = re.findall(r'\{\{[^}]+\}\}', body)
        for placeholder in remaining:
            field_name = placeholder.strip('{}')
            if field_name not in [ni['field'] for ni in needs_input]:
                needs_input.append({
                    "field": field_name,
                    "description": f"Value for {field_name}",
                    "type": "text"
                })

        return DraftResponse(
            body=body,
            template_used=template_name,
            needs_input=needs_input,
            can_adjust=can_adjust,
            variables_used=variables_used,
        )

    def _generate_custom_response(
        self,
        intent: str,
        influencer_name: str,
        classification: Optional[ClassificationResult] = None,
        original_message: Optional[str] = None,
        conversation_history: Optional[list[dict]] = None,
    ) -> DraftResponse:
        """Generate a custom response using Claude when no template fits."""
        system_prompt = f"""You are Pauline, Influencer Marketing Manager at Customuse.
You're drafting an email response to an influencer.

## About Customuse
{self.company.get('product_description', 'Platform for Roblox players to create 3D accessories')}
Website: {self.company.get('website', 'https://customuse.com')}

## Your Communication Style
{self.communication_guide[:2000]}

## Important Guidelines
- Start with "Hi [Name], I hope you are well,"
- Be friendly but professional
- Keep responses concise
- End with the signature block
- NEVER commit to specific rates without approval
- NEVER auto-generate promo codes - use {{{{NEEDS_PROMO_CODE}}}} as placeholder
- NEVER promise specific deadlines - use {{{{NEEDS_DEADLINE}}}} as placeholder

## Signature
{self.signature}"""

        # Build context from history
        history_context = ""
        if conversation_history:
            history_context = "\n\nConversation so far:\n"
            for msg in conversation_history[-5:]:
                direction = "You (Pauline)" if msg["direction"] == "outbound" else "Influencer"
                history_context += f"\n[{direction}]:\n{msg['body'][:400]}...\n"

        summary = classification.summary if classification else "Responding to their message"

        user_prompt = f"""Write a response to {influencer_name}.

Intent: {intent}
Summary: {summary}

Their latest message:
{original_message[:1000] if original_message else 'No message content'}
{history_context}

Write the email body only. Use placeholders like {{{{NEEDS_PROMO_CODE}}}} or {{{{NEEDS_DEADLINE}}}} for anything that needs Pauline's input."""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=800,
                messages=[{"role": "user", "content": user_prompt}],
                system=system_prompt,
            )

            body = response.content[0].text

            # Check for placeholders that need input
            needs_input = []
            if "{{NEEDS_PROMO_CODE}}" in body:
                needs_input.append({
                    "field": "promo_code",
                    "description": "Unique promo code for this influencer",
                    "type": "text"
                })
            if "{{NEEDS_DEADLINE}}" in body:
                needs_input.append({
                    "field": "preview_deadline",
                    "description": "Deadline for content preview",
                    "type": "text"
                })
            if "{{NEEDS_FEEDBACK}}" in body:
                needs_input.append({
                    "field": "feedback",
                    "description": "Specific feedback",
                    "type": "text"
                })

            return DraftResponse(
                body=body,
                template_used=None,  # Custom generated
                needs_input=needs_input,
                can_adjust=["full_response"],  # Can edit entire response
                variables_used={},
            )

        except Exception as e:
            logger.error(f"Claude generation error: {e}")
            # Safe fallback
            fallback = f"""Hi {influencer_name},
I hope you are well,

Thank you for your message! I'll review this and get back to you shortly.

{self.signature}"""
            return DraftResponse(
                body=fallback,
                template_used=None,
                needs_input=[{
                    "field": "full_response",
                    "description": "This is a fallback - please write full response",
                    "type": "text"
                }],
                can_adjust=["full_response"],
                variables_used={},
            )

    # ============================================================
    # Specific response generators (shortcuts for common scenarios)
    # ============================================================

    def generate_initial_response(self, influencer_name: str, platform: str = "YouTube") -> DraftResponse:
        """Generate response to initial interest."""
        return self.generate_response(
            intent="interested",
            influencer_name=influencer_name,
            platform=platform,
        )

    def generate_counter_offer(
        self,
        influencer_name: str,
        their_rate: float,
        our_counter: float,
        use_performance: bool = False,
    ) -> DraftResponse:
        """Generate a counter-offer response."""
        template_name = "counter_offer_performance" if use_performance else "counter_offer_flat"
        template = self.get_template(template_name)

        if template:
            return self._fill_template(
                template_name=template_name,
                template=template,
                influencer_name=influencer_name,
                their_rate=their_rate,
                our_offer=our_counter,
            )

        # Fallback
        return self.generate_response(
            intent="negotiating_price",
            influencer_name=influencer_name,
            their_rate=their_rate,
            our_offer=our_counter,
        )

    def generate_deal_confirmation(
        self,
        influencer_name: str,
        agreed_rate: float,
        promo_code: Optional[str] = None,
        preview_deadline: Optional[str] = None,
    ) -> DraftResponse:
        """Generate deal confirmation with brief."""
        return self.generate_response(
            intent="accepting_offer",
            influencer_name=influencer_name,
            our_offer=agreed_rate,
            promo_code=promo_code,
            preview_deadline=preview_deadline,
        )

    def generate_follow_up(self, influencer_name: str, follow_up_number: int = 1) -> DraftResponse:
        """Generate a follow-up email."""
        template_name = "follow_up_gentle" if follow_up_number == 1 else "follow_up_preview"
        template = self.get_template(template_name)

        if template:
            return self._fill_template(
                template_name=template_name,
                template=template,
                influencer_name=influencer_name,
            )

        # Fallback
        fallback_body = f"""Hi {influencer_name},
I hope you are well,

Circling back on the previous email.

{self.signature}"""

        return DraftResponse(
            body=fallback_body,
            template_used=None,
            needs_input=[],
            can_adjust=[],
            variables_used={},
        )

    def generate_preview_response(
        self,
        influencer_name: str,
        approved: bool,
        promo_code: Optional[str] = None,
        feedback: Optional[str] = None,
    ) -> DraftResponse:
        """Generate response to content preview."""
        if approved:
            template_name = "preview_approved"
        else:
            template_name = "preview_needs_changes"

        template = self.get_template(template_name)
        if template:
            draft = self._fill_template(
                template_name=template_name,
                template=template,
                influencer_name=influencer_name,
                promo_code=promo_code,
            )

            # Add feedback if provided and template has placeholder
            if feedback and "{{NEEDS_FEEDBACK}}" in draft.body:
                draft.body = draft.body.replace("{{NEEDS_FEEDBACK}}", feedback)
                draft.needs_input = [ni for ni in draft.needs_input if ni['field'] != 'feedback']

            return draft

        # Fallback
        return self.generate_response(
            intent="sent_preview",
            influencer_name=influencer_name,
            promo_code=promo_code,
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

    def generate_general_response(
        self,
        influencer_name: str,
        email_content: str,
        classification: Optional[object] = None,
    ) -> str:
        """Generate a general response for any intent not specifically handled."""
        intent = classification.intent if classification else "unknown"

        # Try to use the standard generate_response first
        draft = self.generate_response(
            intent=intent,
            influencer_name=influencer_name,
            classification=classification,
            original_message=email_content,
        )

        return draft.body
