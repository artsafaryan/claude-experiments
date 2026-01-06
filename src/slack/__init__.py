"""Slack integration module."""

from .bot import SlackBot
from .messages import MessageBuilder

__all__ = ["SlackBot", "MessageBuilder"]
