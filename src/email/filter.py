"""Email filtering logic to identify influencer-related emails."""

import re
from dataclasses import dataclass
from typing import Optional

import anthropic

from ..utils.config import get_settings, get_app_config
from ..utils.logging import get_logger
from ..database.repository import get_repository

logger = get_logger("email_filter")


@dataclass
class FilterResult:
    """Result of email filtering."""
    should_process: bool
    reason: str
    confidence: float = 1.0  # 1.0 = definite, lower = AI-based decision


class EmailFilter:
    """
    Multi-layer email filter to identify influencer-related emails.

    Layer 1: Blocklist - Immediately skip known non-influencer emails
    Layer 2: Allowlist - Immediately process known influencer conversations
    Layer 3: AI Screening - Quick check for unknown senders
    """

    def __init__(self):
        self.settings = get_settings()
        self.config = get_app_config()
        self.repo = get_repository()
        self.claude = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)

        # Load filtering rules from config
        self.filter_config = self.config.get("email_filtering", {})
        self.blocked_domains = set(self.filter_config.get("blocked_domains", []))
        self.blocked_sender_patterns = self.filter_config.get("blocked_sender_patterns", [])
        self.blocked_subject_patterns = self.filter_config.get("blocked_subject_patterns", [])
        self.influencer_subject_hints = self.filter_config.get("influencer_subject_hints", [])
        self.company_domain = self.filter_config.get("company_domain", "")

    def should_process(
        self,
        from_email: str,
        subject: str,
        body: str,
        thread_id: Optional[str] = None,
    ) -> FilterResult:
        """
        Determine if an email should be processed by the system.

        Returns FilterResult with decision and reasoning.
        """
        from_email_lower = from_email.lower()
        subject_lower = subject.lower()

        # ========== LAYER 1: BLOCKLIST ==========
        # These are definitely NOT influencer emails

        # Check blocked domains
        domain = self._extract_domain(from_email_lower)
        if domain in self.blocked_domains:
            logger.debug(f"Skipping email from blocked domain: {domain}")
            return FilterResult(
                should_process=False,
                reason=f"Blocked domain: {domain}",
                confidence=1.0
            )

        # Check blocked sender patterns
        for pattern in self.blocked_sender_patterns:
            if pattern.lower() in from_email_lower:
                logger.debug(f"Skipping email matching blocked pattern: {pattern}")
                return FilterResult(
                    should_process=False,
                    reason=f"Blocked sender pattern: {pattern}",
                    confidence=1.0
                )

        # Check company domain (internal emails)
        if self.company_domain and domain == self.company_domain.lower():
            logger.debug(f"Skipping internal company email from {domain}")
            return FilterResult(
                should_process=False,
                reason="Internal company email",
                confidence=1.0
            )

        # Check blocked subject patterns
        for pattern in self.blocked_subject_patterns:
            try:
                if re.search(pattern, subject, re.IGNORECASE):
                    logger.debug(f"Skipping email with blocked subject pattern: {pattern}")
                    return FilterResult(
                        should_process=False,
                        reason=f"Blocked subject pattern: {pattern}",
                        confidence=1.0
                    )
            except re.error:
                # Invalid regex, skip this pattern
                pass

        # ========== LAYER 2: ALLOWLIST ==========
        # These are definitely influencer emails

        # Check if sender is a known influencer in our database
        influencer = self.repo.get_influencer_by_email(from_email)
        if influencer:
            logger.debug(f"Processing email from known influencer: {from_email}")
            return FilterResult(
                should_process=True,
                reason=f"Known influencer: {influencer.name}",
                confidence=1.0
            )

        # Check if this is part of an existing conversation we're tracking
        if thread_id:
            conversation = self.repo.get_conversation_by_thread_id(thread_id)
            if conversation:
                logger.debug(f"Processing email in existing conversation thread")
                return FilterResult(
                    should_process=True,
                    reason="Existing conversation thread",
                    confidence=1.0
                )

        # Check if subject has influencer-related hints
        has_influencer_hints = any(
            hint.lower() in subject_lower
            for hint in self.influencer_subject_hints
        )

        # ========== LAYER 3: AI SCREENING ==========
        # For unknown senders, use AI to determine if it's influencer-related

        ai_result = self._ai_screen_email(from_email, subject, body, has_influencer_hints)
        return ai_result

    def _extract_domain(self, email: str) -> str:
        """Extract domain from email address."""
        if "@" in email:
            return email.split("@")[1].lower()
        return ""

    def _ai_screen_email(
        self,
        from_email: str,
        subject: str,
        body: str,
        has_subject_hints: bool,
    ) -> FilterResult:
        """
        Use AI to determine if an email is influencer-related.

        This is a quick screening check, not full classification.
        """
        try:
            # Truncate body to save tokens - just need enough context for decision
            body_preview = body[:500] if len(body) > 500 else body

            prompt = f"""You are filtering emails for an influencer marketing automation system.
Your job is to determine if this email is from an influencer or content creator discussing a potential brand collaboration, partnership, or sponsored content opportunity.

ONLY say YES if the email is clearly:
- From an individual creator/influencer (not a company or service)
- Discussing brand partnerships, collaborations, sponsored content, or rates
- Related to content creation for marketing purposes (Instagram, TikTok, YouTube, etc.)

Say NO if the email is:
- From a company, service, or automated system
- About internal business matters, receipts, notifications
- A newsletter, marketing email, or promotional content
- From a colleague or business contact (not an influencer)
- About anything unrelated to influencer marketing

Email details:
From: {from_email}
Subject: {subject}

Body preview:
{body_preview}

Answer with ONLY "YES" or "NO" followed by a brief reason (max 10 words).
Example: YES - Creator discussing Instagram post rates
Example: NO - Automated billing notification"""

            response = self.claude.messages.create(
                model="claude-3-5-haiku-20241022",  # Haiku for cost-effective filtering
                max_tokens=50,
                messages=[{"role": "user", "content": prompt}]
            )

            answer = response.content[0].text.strip().upper()

            # Parse the response
            is_influencer = answer.startswith("YES")
            reason = answer.split("-", 1)[1].strip() if "-" in answer else answer

            logger.info(
                f"AI screening for {from_email}: "
                f"{'PROCESS' if is_influencer else 'SKIP'} - {reason}"
            )

            return FilterResult(
                should_process=is_influencer,
                reason=f"AI screening: {reason}",
                confidence=0.85 if is_influencer else 0.9  # Higher confidence for rejections
            )

        except Exception as e:
            logger.error(f"AI screening failed: {e}")
            # If AI screening fails and there were subject hints, process it
            # Otherwise, skip to avoid processing random emails
            if has_subject_hints:
                return FilterResult(
                    should_process=True,
                    reason="AI screening failed, but subject has influencer hints",
                    confidence=0.5
                )
            return FilterResult(
                should_process=False,
                reason=f"AI screening failed: {e}",
                confidence=0.5
            )


# Singleton instance
_filter: Optional[EmailFilter] = None


def get_email_filter() -> EmailFilter:
    """Get or create the email filter singleton."""
    global _filter
    if _filter is None:
        _filter = EmailFilter()
    return _filter
