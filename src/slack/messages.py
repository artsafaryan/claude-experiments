"""Slack message formatting and building."""

from typing import Optional
from datetime import datetime


class MessageBuilder:
    """Builds formatted Slack messages."""

    @staticmethod
    def build_daily_summary(
        new_responses: list[dict],
        pending_follow_ups: list[dict],
        pending_approvals: int,
    ) -> list[dict]:
        """Build the daily summary message blocks."""
        today = datetime.now().strftime("%b %d, %Y")

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"📊 Influencer Summary - {today}",
                    "emoji": True,
                },
            },
            {"type": "divider"},
        ]

        # New responses section
        if new_responses:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*New Responses ({len(new_responses)})*",
                    },
                }
            )

            response_text = ""
            for resp in new_responses[:10]:  # Limit to 10
                icon = MessageBuilder._get_intent_icon(resp.get("intent", ""))
                response_text += f"{icon} *{resp['name']}* ({resp.get('followers', 'N/A')} followers) - {resp.get('summary', 'New message')}\n"

            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": response_text.strip()},
                }
            )

        # Pending follow-ups section
        if pending_follow_ups:
            blocks.append({"type": "divider"})
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Pending Follow-ups ({len(pending_follow_ups)})*",
                    },
                }
            )

            follow_up_text = ""
            for fu in pending_follow_ups[:5]:
                days = fu.get("days_waiting", "?")
                follow_up_text += f"• *{fu['name']}* - No response in {days} days\n"

            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": follow_up_text.strip()},
                }
            )

        # Pending approvals section
        if pending_approvals > 0:
            blocks.append({"type": "divider"})
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{pending_approvals} drafted responses ready for approval* 👇",
                    },
                }
            )

        return blocks

    @staticmethod
    def build_approval_card(
        approval_id: str,
        influencer_name: str,
        influencer_handle: Optional[str],
        their_message: str,
        draft_response: str,
        response_type: str,
        their_rate: Optional[float] = None,
        our_counter: Optional[float] = None,
        priority: str = "medium",
    ) -> list[dict]:
        """Build an approval card for a single response."""
        priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
            priority, "🟡"
        )

        # Truncate messages for display
        their_message_truncated = (
            their_message[:300] + "..." if len(their_message) > 300 else their_message
        )
        draft_truncated = (
            draft_response[:400] + "..." if len(draft_response) > 400 else draft_response
        )

        handle_text = f" (@{influencer_handle})" if influencer_handle else ""

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{priority_emoji} *Response to {influencer_name}{handle_text}*\n_{response_type.replace('_', ' ').title()}_",
                },
            },
        ]

        # Add pricing context if negotiating
        if their_rate or our_counter:
            price_text = ""
            if their_rate:
                price_text += f"Their ask: *${their_rate:,.0f}*"
            if our_counter:
                price_text += f" → Our counter: *${our_counter:,.0f}*"
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": price_text}],
                }
            )

        # Their message
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Their message:*\n>{their_message_truncated.replace(chr(10), chr(10) + '>')}",
                },
            }
        )

        # Our drafted response
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Drafted response:*\n```{draft_truncated}```",
                },
            }
        )

        # Action buttons
        blocks.append(
            {
                "type": "actions",
                "block_id": f"approval_actions_{approval_id}",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Approve", "emoji": True},
                        "style": "primary",
                        "action_id": "approve_response",
                        "value": approval_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✏️ Edit", "emoji": True},
                        "action_id": "edit_response",
                        "value": approval_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "❌ Reject", "emoji": True},
                        "style": "danger",
                        "action_id": "reject_response",
                        "value": approval_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "👀 View Full", "emoji": True},
                        "action_id": "view_full",
                        "value": approval_id,
                    },
                ],
            }
        )

        blocks.append({"type": "divider"})

        return blocks

    @staticmethod
    def build_approval_batch(approvals: list[dict]) -> list[dict]:
        """Build a batch of approval cards."""
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"📧 {len(approvals)} Responses Ready for Approval",
                    "emoji": True,
                },
            },
            {"type": "divider"},
        ]

        for approval in approvals:
            blocks.extend(
                MessageBuilder.build_approval_card(
                    approval_id=approval["id"],
                    influencer_name=approval["influencer_name"],
                    influencer_handle=approval.get("influencer_handle"),
                    their_message=approval["their_message"],
                    draft_response=approval["draft_response"],
                    response_type=approval["response_type"],
                    their_rate=approval.get("their_rate"),
                    our_counter=approval.get("our_counter"),
                    priority=approval.get("priority", "medium"),
                )
            )

        # Bulk actions at the bottom
        blocks.append(
            {
                "type": "actions",
                "block_id": "bulk_actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "✅ Approve All",
                            "emoji": True,
                        },
                        "style": "primary",
                        "action_id": "approve_all",
                        "confirm": {
                            "title": {"type": "plain_text", "text": "Approve All?"},
                            "text": {
                                "type": "mrkdwn",
                                "text": f"This will send {len(approvals)} emails. Are you sure?",
                            },
                            "confirm": {"type": "plain_text", "text": "Yes, send all"},
                            "deny": {"type": "plain_text", "text": "Cancel"},
                        },
                    },
                ],
            }
        )

        return blocks

    @staticmethod
    def build_edit_modal(
        approval_id: str,
        influencer_name: str,
        current_draft: str,
    ) -> dict:
        """Build modal for editing a response."""
        return {
            "type": "modal",
            "callback_id": f"edit_modal_{approval_id}",
            "title": {"type": "plain_text", "text": "Edit Response"},
            "submit": {"type": "plain_text", "text": "Save & Send"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Editing response to *{influencer_name}*",
                    },
                },
                {
                    "type": "input",
                    "block_id": "response_input",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "response_text",
                        "multiline": True,
                        "initial_value": current_draft,
                    },
                    "label": {"type": "plain_text", "text": "Email Response"},
                },
            ],
            "private_metadata": approval_id,
        }

    @staticmethod
    def build_confirmation_message(
        action: str,
        influencer_name: str,
        details: Optional[str] = None,
    ) -> list[dict]:
        """Build confirmation message after an action."""
        icons = {
            "approved": "✅",
            "rejected": "❌",
            "edited": "✏️",
            "sent": "📤",
        }
        icon = icons.get(action, "ℹ️")

        text = f"{icon} Response to *{influencer_name}* {action}"
        if details:
            text += f"\n_{details}_"

        return [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text},
            }
        ]

    @staticmethod
    def _get_intent_icon(intent: str) -> str:
        """Get emoji icon for intent type."""
        icons = {
            "accepting_offer": "🎉",
            "negotiating_price": "💰",
            "asking_question": "❓",
            "interested": "👍",
            "declining_offer": "👎",
            "submitting_content": "📎",
            "requesting_info": "📋",
            "out_of_office": "🏖️",
        }
        return icons.get(intent, "📧")
