"""Email handling module."""

from .gmail_client import GmailClient
from .processor import EmailProcessor

__all__ = ["GmailClient", "EmailProcessor"]
