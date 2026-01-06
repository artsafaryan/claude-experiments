"""Response generation using Claude and templates."""

from typing import Optional

import anthropic

from ..utils.config import get_settings, get_templates, get_app_config
from ..utils.logging import get_logger
from .classifier import ClassificationResult

logger = get_logger("responder")


class ResponseGenerator:
    """Generates email responses using templates and Claude."""

    def __init__(self):
        self.settings = get_settings()
        self.templates = get_templates()
        self.app_config = get_app_config()
        self.client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        self.brand = self.templates.get("brand", {})

    def _get_template(self, template_name: str) -> Optional[dict]:
        """Get a template by name."""
        return self.templates.get("templates", {}).get(template_name)

    def _fill_template(self, template_body: str, **kwargs) -> str:
        """Fill in template placeholders."""
        result = template_body

        # Add brand defaults
        kwargs.setdefault("brand_name", self.brand.get("name", "Our Brand"))
        kwargs.setdefault("contact_name", self.brand.get("contact_name", "The Team"))

        for key, value in kwargs.items():
            placeholder = "{" + key + "}"
            if value is not None:
                result = result.replace(placeholder, str(value))

        return result

    def generate_initial_outreach(
        self,
        influencer_name: str,
        initial_rate: float,
        content_type: str = "Instagram Reel",
        content_requirements: str = "1 Instagram Reel featuring our product",
        timeline: str = "the next 2-3 weeks",
    ) -> str:
        """Generate initial outreach email."""
        template = self._get_template("initial_outreach")
        if not template:
            return self._generate_with_claude(
                "initial outreach", influencer_name=influencer_name, rate=initial_rate
            )

        return self._fill_template(
            template["body"],
            influencer_name=influencer_name,
            initial_rate=initial_rate,
            content_type=content_type,
            content_requirements=content_requirements,
            timeline=timeline,
        )

    def generate_counter_offer(
        self,
        influencer_name: str,
        their_rate: float,
        our_counter: float,
        content_description: str = "one Instagram Reel",
    ) -> str:
        """Generate a counter-offer response."""
        # Check if we should accept their rate
        if our_counter >= their_rate:
            return self.generate_accept_rate(influencer_name, their_rate)

        template = self._get_template("negotiation_counter")
        if not template:
            return self._generate_with_claude(
                "counter offer",
                influencer_name=influencer_name,
                their_rate=their_rate,
                our_counter=our_counter,
            )

        return self._fill_template(
            template["body"],
            influencer_name=influencer_name,
            their_rate=f"${their_rate:,.0f}",
            our_counter=f"{our_counter:,.0f}",
            content_description=content_description,
        )

    def generate_accept_rate(
        self,
        influencer_name: str,
        their_rate: float,
    ) -> str:
        """Generate acceptance of their rate."""
        template = self._get_template("negotiation_accept_rate")
        if not template:
            return self._generate_with_claude(
                "accept rate", influencer_name=influencer_name, rate=their_rate
            )

        return self._fill_template(
            template["body"],
            influencer_name=influencer_name,
            their_rate=f"${their_rate:,.0f}",
        )

    def generate_max_offer_reached(
        self,
        influencer_name: str,
        our_max: float,
    ) -> str:
        """Generate response when we've reached our max offer."""
        template = self._get_template("negotiation_max_reached")
        if not template:
            return self._generate_with_claude(
                "max offer reached", influencer_name=influencer_name, max_offer=our_max
            )

        return self._fill_template(
            template["body"],
            influencer_name=influencer_name,
            our_max=f"{our_max:,.0f}",
        )

    def generate_question_response(
        self,
        influencer_name: str,
        question_type: str,
        question_content: str,
    ) -> str:
        """Generate response to a question."""
        # Try to use appropriate template based on question type
        template_map = {
            "timeline": "timeline_info",
            "format": "format_requirements",
        }

        template_name = template_map.get(question_type)
        if template_name:
            template = self._get_template(template_name)
            if template:
                return self._fill_template(
                    template["body"],
                    influencer_name=influencer_name,
                    # Add sensible defaults - these would come from campaign config
                    creation_period="2 weeks",
                    posting_window="flexible within the campaign period",
                    draft_deadline="1 week before posting",
                    platform="Instagram",
                    content_type="Reel",
                    duration="30-60 seconds",
                    aspect_ratio="9:16 (vertical)",
                    brand_handle="yourbrand",
                    hashtags="#ad #sponsored",
                    additional_requirements="Natural integration with your content style",
                )

        # Fall back to Claude for custom response
        return self._generate_with_claude(
            "answer question",
            influencer_name=influencer_name,
            question=question_content,
        )

    def generate_deal_confirmation(
        self,
        influencer_name: str,
        agreed_rate: float,
        posting_date: str = "to be confirmed",
        draft_deadline: str = "1 week before posting",
        payment_terms: str = "30 days",
    ) -> str:
        """Generate deal confirmation email."""
        template = self._get_template("deal_confirmed")
        if not template:
            return self._generate_with_claude(
                "deal confirmation", influencer_name=influencer_name, rate=agreed_rate
            )

        return self._fill_template(
            template["body"],
            influencer_name=influencer_name,
            agreed_rate=f"{agreed_rate:,.0f}",
            posting_date=posting_date,
            draft_deadline=draft_deadline,
            payment_terms=payment_terms,
        )

    def generate_content_received_response(
        self,
        influencer_name: str,
    ) -> str:
        """Generate response acknowledging content submission."""
        template = self._get_template("content_received")
        if not template:
            return self._generate_with_claude(
                "content received acknowledgment", influencer_name=influencer_name
            )

        return self._fill_template(
            template["body"],
            influencer_name=influencer_name,
        )

    def generate_follow_up(
        self,
        influencer_name: str,
        follow_up_number: int = 1,
    ) -> str:
        """Generate follow-up email."""
        template_name = f"follow_up_{'first' if follow_up_number == 1 else 'second'}"
        template = self._get_template(template_name)

        if not template:
            return self._generate_with_claude(
                f"follow up #{follow_up_number}", influencer_name=influencer_name
            )

        return self._fill_template(
            template["body"],
            influencer_name=influencer_name,
        )

    def generate_general_response(
        self,
        influencer_name: str,
        email_content: str,
        classification: ClassificationResult,
    ) -> str:
        """Generate a general contextual response using Claude."""
        return self._generate_with_claude(
            f"response to {classification.intent}",
            influencer_name=influencer_name,
            their_message=email_content,
            context=classification.summary,
        )

    def _generate_with_claude(self, response_type: str, **context) -> str:
        """Generate a custom response using Claude."""
        system_prompt = f"""You are a professional marketing coordinator responding to influencers.
Write friendly, professional emails that are concise but warm.

Brand: {self.brand.get('name', 'Our Brand')}
Your name: {self.brand.get('contact_name', 'The Team')}

Guidelines:
- Be friendly and professional
- Keep responses concise (under 150 words)
- Don't be overly formal or stiff
- Show genuine interest in working together
- Don't make promises about rates or terms without explicit approval
- End with a clear next step or question"""

        context_str = "\n".join(f"- {k}: {v}" for k, v in context.items())

        user_prompt = f"""Write a {response_type} email.

Context:
{context_str}

Write only the email body (no subject line). Be natural and professional."""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[
                    {"role": "user", "content": user_prompt}
                ],
                system=system_prompt,
            )

            return response.content[0].text

        except Exception as e:
            logger.error(f"Claude generation error: {e}")
            # Return a safe fallback
            name = context.get("influencer_name", "there")
            return f"""Hi {name},

Thank you for your message! I'll review this and get back to you shortly.

Best,
{self.brand.get('contact_name', 'The Team')}"""
