"""Enhanced Slack message formatting for Customuse influencer workflow."""

from typing import Optional
from datetime import datetime


class MessageBuilder:
    """Builds formatted Slack messages with rich approval cards."""

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
                response_text += f"{icon} *{resp['name']}* - {resp.get('summary', 'New message')}\n"

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
        needs_input: Optional[list] = None,
        template_used: Optional[str] = None,
        conversation_stage: Optional[str] = None,
        platform: Optional[str] = None,
    ) -> list[dict]:
        """Build an enhanced approval card for a single response."""
        priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
            priority, "🟡"
        )
        stage_emoji = MessageBuilder._get_stage_emoji(response_type)

        # Truncate messages for display
        their_message_truncated = (
            their_message[:400] + "..." if len(their_message) > 400 else their_message
        )
        draft_truncated = (
            draft_response[:500] + "..." if len(draft_response) > 500 else draft_response
        )

        handle_text = f" (@{influencer_handle})" if influencer_handle else ""
        platform_text = f" • {platform}" if platform else ""

        # Header block
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{priority_emoji} *{influencer_name}{handle_text}*{platform_text}\n{stage_emoji} _{response_type.replace('_', ' ').title()}_",
                },
            },
        ]

        # Context line - pricing info if negotiating
        context_elements = []
        if their_rate:
            context_elements.append({"type": "mrkdwn", "text": f"Their ask: *${their_rate:,.0f}*"})
        if our_counter:
            context_elements.append({"type": "mrkdwn", "text": f"Our offer: *${our_counter:,.0f}*"})
        if template_used:
            context_elements.append({"type": "mrkdwn", "text": f"📝 Template: _{template_used}_"})

        if context_elements:
            blocks.append({
                "type": "context",
                "elements": context_elements,
            })

        # Their message
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*📩 Their message:*\n>{their_message_truncated.replace(chr(10), chr(10) + '>')}",
                },
            }
        )

        # Our drafted response
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*📤 Draft response:*\n```{draft_truncated}```",
                },
            }
        )

        # ========== NEEDS INPUT SECTION ==========
        # Show what Pauline needs to provide before approving
        if needs_input:
            needs_input_text = "*⚠️ This response needs your input:*\n"
            for item in needs_input:
                field = item.get("field", "unknown")
                description = item.get("description", field)

                if field == "promo_code":
                    needs_input_text += f"• 🎟️ *Promo Code* - {description}\n"
                elif field == "preview_deadline":
                    needs_input_text += f"• 📅 *Deadline* - {description}\n"
                elif field == "feedback":
                    needs_input_text += f"• 💬 *Feedback* - {description}\n"
                elif field == "our_offer":
                    needs_input_text += f"• 💰 *Offer Amount* - {description}\n"
                else:
                    needs_input_text += f"• {description}\n"

            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": needs_input_text.strip()},
            })

            # Add "Provide Input" button if there are missing inputs
            blocks.append({
                "type": "actions",
                "block_id": f"input_actions_{approval_id}",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "📝 Provide Missing Info", "emoji": True},
                        "action_id": "provide_input",
                        "value": approval_id,
                    },
                ],
            })

        # ========== ACTION BUTTONS ==========
        action_elements = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "✅ Approve & Send", "emoji": True},
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
        ]

        # Add adjustment buttons based on response type
        if response_type in ["counter_offer_flat", "counter_offer_performance", "negotiating_price"]:
            action_elements.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "💰 Adjust Offer", "emoji": True},
                "action_id": "adjust_offer",
                "value": approval_id,
            })

        if response_type in ["counter_offer_flat", "negotiating_price"]:
            action_elements.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "📊 Use Performance Deal", "emoji": True},
                "action_id": "switch_to_performance",
                "value": approval_id,
            })

        action_elements.extend([
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "❌ Reject", "emoji": True},
                "style": "danger",
                "action_id": "reject_response",
                "value": approval_id,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "👀 Full Details", "emoji": True},
                "action_id": "view_full",
                "value": approval_id,
            },
        ])

        blocks.append({
            "type": "actions",
            "block_id": f"approval_actions_{approval_id}",
            "elements": action_elements[:5],  # Slack limits to 5 elements per actions block
        })

        # If we have more than 5 action elements, add another actions block
        if len(action_elements) > 5:
            blocks.append({
                "type": "actions",
                "block_id": f"extra_actions_{approval_id}",
                "elements": action_elements[5:],
            })

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
                    needs_input=approval.get("needs_input"),
                    template_used=approval.get("template_used"),
                    platform=approval.get("platform"),
                )
            )

        # Bulk actions at the bottom (only if no inputs needed)
        has_inputs_needed = any(a.get("needs_input") for a in approvals)

        if not has_inputs_needed:
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
    def build_input_modal(
        approval_id: str,
        influencer_name: str,
        needs_input: list,
        current_draft: str,
    ) -> dict:
        """Build modal for providing missing input values."""
        modal_blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"📝 *Provide information for response to {influencer_name}*",
                },
            },
            {"type": "divider"},
        ]

        # Add input fields for each required item
        for item in needs_input:
            field = item.get("field", "unknown")
            description = item.get("description", field)
            field_type = item.get("type", "text")

            if field == "promo_code":
                modal_blocks.append({
                    "type": "input",
                    "block_id": f"input_{field}",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": f"value_{field}",
                        "placeholder": {"type": "plain_text", "text": "e.g., CREATOR25"},
                    },
                    "label": {"type": "plain_text", "text": "🎟️ Promo Code"},
                    "hint": {"type": "plain_text", "text": "The unique code for this influencer's audience"},
                })
            elif field == "preview_deadline":
                modal_blocks.append({
                    "type": "input",
                    "block_id": f"input_{field}",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": f"value_{field}",
                        "placeholder": {"type": "plain_text", "text": "e.g., Friday EOD, Jan 15th"},
                    },
                    "label": {"type": "plain_text", "text": "📅 Preview Deadline"},
                    "hint": {"type": "plain_text", "text": "When do you need the content preview?"},
                })
            elif field == "feedback":
                modal_blocks.append({
                    "type": "input",
                    "block_id": f"input_{field}",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": f"value_{field}",
                        "multiline": True,
                        "placeholder": {"type": "plain_text", "text": "e.g., Please mention the app name earlier in the video"},
                    },
                    "label": {"type": "plain_text", "text": "💬 Feedback on Preview"},
                    "hint": {"type": "plain_text", "text": "What changes are needed?"},
                })
            elif field == "our_offer":
                modal_blocks.append({
                    "type": "input",
                    "block_id": f"input_{field}",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": f"value_{field}",
                        "placeholder": {"type": "plain_text", "text": "e.g., 200"},
                    },
                    "label": {"type": "plain_text", "text": "💰 Our Offer (USD)"},
                    "hint": {"type": "plain_text", "text": "The amount we're offering"},
                })
            else:
                modal_blocks.append({
                    "type": "input",
                    "block_id": f"input_{field}",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": f"value_{field}",
                    },
                    "label": {"type": "plain_text", "text": description},
                })

        # Show current draft for reference
        modal_blocks.append({"type": "divider"})
        modal_blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Current draft (placeholders will be filled):*\n```{current_draft[:1000]}```",
            },
        })

        return {
            "type": "modal",
            "callback_id": "input_modal",
            "private_metadata": approval_id,
            "title": {"type": "plain_text", "text": "Provide Info", "emoji": True},
            "submit": {"type": "plain_text", "text": "Update & Send", "emoji": True},
            "close": {"type": "plain_text", "text": "Cancel", "emoji": True},
            "blocks": modal_blocks,
        }

    @staticmethod
    def build_adjust_offer_modal(
        approval_id: str,
        influencer_name: str,
        current_offer: Optional[float],
        their_rate: Optional[float],
    ) -> dict:
        """Build modal for adjusting the offer amount."""
        context_text = ""
        if their_rate:
            context_text += f"Their ask: *${their_rate:,.0f}*\n"
        if current_offer:
            context_text += f"Current offer: *${current_offer:,.0f}*"

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"💰 *Adjust offer for {influencer_name}*",
                },
            },
        ]

        if context_text:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": context_text}],
            })

        blocks.append({
            "type": "input",
            "block_id": "new_offer",
            "element": {
                "type": "plain_text_input",
                "action_id": "offer_value",
                "initial_value": str(int(current_offer)) if current_offer else "",
                "placeholder": {"type": "plain_text", "text": "Enter new offer amount"},
            },
            "label": {"type": "plain_text", "text": "New Offer (USD)"},
        })

        return {
            "type": "modal",
            "callback_id": "adjust_offer_modal",
            "private_metadata": approval_id,
            "title": {"type": "plain_text", "text": "Adjust Offer", "emoji": True},
            "submit": {"type": "plain_text", "text": "Update Draft", "emoji": True},
            "close": {"type": "plain_text", "text": "Cancel", "emoji": True},
            "blocks": blocks,
        }

    @staticmethod
    def build_edit_modal(
        approval_id: str,
        influencer_name: str,
        current_draft: str,
    ) -> dict:
        """Build modal for editing a response."""
        return {
            "type": "modal",
            "callback_id": "edit_modal",
            "private_metadata": approval_id,
            "title": {"type": "plain_text", "text": "Edit Response"},
            "submit": {"type": "plain_text", "text": "Save & Send"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"✏️ Editing response to *{influencer_name}*",
                    },
                },
                {"type": "divider"},
                {
                    "type": "input",
                    "block_id": "response_input",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "response_text",
                        "multiline": True,
                        "initial_value": current_draft,
                        "min_length": 10,
                    },
                    "label": {"type": "plain_text", "text": "Email Response"},
                    "hint": {"type": "plain_text", "text": "Edit the email content. It will be sent immediately after saving."},
                },
            ],
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
            "updated": "🔄",
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
            "sent_preview": "🎬",
            "content_published": "🚀",
            "needs_pro_access": "🔑",
            "sent_username": "👤",
            "sent_payment_details": "💳",
            "delayed": "⏰",
            "out_of_office": "🏖️",
        }
        return icons.get(intent, "📧")

    @staticmethod
    def _get_stage_emoji(response_type: str) -> str:
        """Get emoji for conversation stage."""
        stages = {
            "request_insights_and_rate": "1️⃣",
            "request_rate_only": "1️⃣",
            "request_insights_only": "1️⃣",
            "counter_offer_flat": "2️⃣",
            "counter_offer_performance": "2️⃣",
            "hold_firm_on_rate": "2️⃣",
            "increase_offer_slightly": "2️⃣",
            "deal_accepted_send_brief": "3️⃣",
            "grant_pro_access": "3️⃣",
            "request_username": "3️⃣",
            "confirm_payment_sent": "3️⃣",
            "preview_approved": "4️⃣",
            "preview_needs_changes": "4️⃣",
            "video_live_confirmation": "5️⃣",
            "follow_up_gentle": "🔄",
        }
        return stages.get(response_type, "📧")
