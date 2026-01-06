"""Gmail API client for reading and sending emails."""

import base64
import os
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from dataclasses import dataclass

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..utils.config import get_settings, get_app_config
from ..utils.logging import get_logger

logger = get_logger("gmail")


@dataclass
class EmailMessage:
    """Represents an email message."""

    message_id: str
    thread_id: str
    from_email: str
    to_email: str
    subject: str
    body: str
    body_html: Optional[str]
    date: datetime
    labels: list[str]
    is_unread: bool


class GmailClient:
    """Client for Gmail API operations."""

    SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.modify",
    ]

    def __init__(
        self,
        credentials_file: Optional[str] = None,
        token_file: Optional[str] = None,
    ):
        self.settings = get_settings()
        self.credentials_file = credentials_file or self.settings.gmail_credentials_file
        self.token_file = token_file or self.settings.gmail_token_file
        self.service = None
        self._user_email = None

    def authenticate(self) -> bool:
        """Authenticate with Gmail API using OAuth."""
        creds = None

        # Load existing token if available
        if os.path.exists(self.token_file):
            creds = Credentials.from_authorized_user_file(self.token_file, self.SCOPES)

        # If no valid credentials, get new ones
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired credentials")
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_file):
                    logger.error(
                        f"Credentials file not found: {self.credentials_file}. "
                        "Please download from Google Cloud Console."
                    )
                    return False

                logger.info("Starting OAuth flow - browser will open")
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, self.SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save credentials for future use
            with open(self.token_file, "w") as token:
                token.write(creds.to_json())
            logger.info(f"Credentials saved to {self.token_file}")

        self.service = build("gmail", "v1", credentials=creds)
        logger.info("Gmail API authenticated successfully")
        return True

    def get_user_email(self) -> str:
        """Get the authenticated user's email address."""
        if self._user_email:
            return self._user_email

        if not self.service:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        profile = self.service.users().getProfile(userId="me").execute()
        self._user_email = profile["emailAddress"]
        return self._user_email

    def get_unread_messages(
        self, max_results: int = 50, label_ids: Optional[list[str]] = None
    ) -> list[EmailMessage]:
        """Fetch unread messages from inbox."""
        if not self.service:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        label_ids = label_ids or ["INBOX", "UNREAD"]

        try:
            results = (
                self.service.users()
                .messages()
                .list(userId="me", labelIds=label_ids, maxResults=max_results)
                .execute()
            )

            messages = results.get("messages", [])
            logger.info(f"Found {len(messages)} unread messages")

            return [self._get_message_details(msg["id"]) for msg in messages]

        except HttpError as e:
            logger.error(f"Error fetching messages: {e}")
            return []

    def get_thread_messages(self, thread_id: str) -> list[EmailMessage]:
        """Get all messages in a thread."""
        if not self.service:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        try:
            thread = (
                self.service.users()
                .threads()
                .get(userId="me", id=thread_id, format="full")
                .execute()
            )

            return [
                self._parse_message(msg) for msg in thread.get("messages", [])
            ]

        except HttpError as e:
            logger.error(f"Error fetching thread {thread_id}: {e}")
            return []

    def _get_message_details(self, message_id: str) -> EmailMessage:
        """Get full details of a specific message."""
        message = (
            self.service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        return self._parse_message(message)

    def _parse_message(self, message: dict) -> EmailMessage:
        """Parse a Gmail API message into our EmailMessage format."""
        headers = {h["name"]: h["value"] for h in message["payload"]["headers"]}

        # Extract body
        body = ""
        body_html = None

        payload = message["payload"]
        if "body" in payload and payload["body"].get("data"):
            body = self._decode_body(payload["body"]["data"])
        elif "parts" in payload:
            body, body_html = self._extract_body_from_parts(payload["parts"])

        # Parse date
        date_str = headers.get("Date", "")
        try:
            # Handle various date formats
            from email.utils import parsedate_to_datetime
            date = parsedate_to_datetime(date_str)
        except Exception:
            date = datetime.utcnow()

        return EmailMessage(
            message_id=message["id"],
            thread_id=message["threadId"],
            from_email=self._extract_email(headers.get("From", "")),
            to_email=self._extract_email(headers.get("To", "")),
            subject=headers.get("Subject", ""),
            body=body,
            body_html=body_html,
            date=date,
            labels=message.get("labelIds", []),
            is_unread="UNREAD" in message.get("labelIds", []),
        )

    def _extract_body_from_parts(
        self, parts: list[dict]
    ) -> tuple[str, Optional[str]]:
        """Extract plain text and HTML body from message parts."""
        body = ""
        body_html = None

        for part in parts:
            mime_type = part.get("mimeType", "")

            if mime_type == "text/plain" and "data" in part.get("body", {}):
                body = self._decode_body(part["body"]["data"])
            elif mime_type == "text/html" and "data" in part.get("body", {}):
                body_html = self._decode_body(part["body"]["data"])
            elif "parts" in part:
                # Recursively handle nested parts
                nested_body, nested_html = self._extract_body_from_parts(part["parts"])
                if nested_body:
                    body = nested_body
                if nested_html:
                    body_html = nested_html

        return body, body_html

    def _decode_body(self, data: str) -> str:
        """Decode base64url encoded body."""
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    def _extract_email(self, header_value: str) -> str:
        """Extract email address from header like 'Name <email@example.com>'."""
        if "<" in header_value and ">" in header_value:
            return header_value.split("<")[1].split(">")[0]
        return header_value

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        thread_id: Optional[str] = None,
        reply_to_message_id: Optional[str] = None,
    ) -> Optional[str]:
        """Send an email, optionally as a reply to an existing thread."""
        if not self.service:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        try:
            message = MIMEMultipart("alternative")
            message["to"] = to
            message["subject"] = subject

            # Add References and In-Reply-To headers for threading
            if reply_to_message_id:
                message["In-Reply-To"] = reply_to_message_id
                message["References"] = reply_to_message_id

            # Add plain text body
            message.attach(MIMEText(body, "plain"))

            # Encode the message
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

            body_data = {"raw": raw}
            if thread_id:
                body_data["threadId"] = thread_id

            sent_message = (
                self.service.users()
                .messages()
                .send(userId="me", body=body_data)
                .execute()
            )

            logger.info(f"Email sent successfully. Message ID: {sent_message['id']}")
            return sent_message["id"]

        except HttpError as e:
            logger.error(f"Error sending email: {e}")
            return None

    def mark_as_read(self, message_id: str) -> bool:
        """Mark a message as read."""
        if not self.service:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        try:
            self.service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()
            return True
        except HttpError as e:
            logger.error(f"Error marking message as read: {e}")
            return False

    def add_label(self, message_id: str, label_name: str) -> bool:
        """Add a label to a message."""
        if not self.service:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        try:
            # First, get or create the label
            labels_response = self.service.users().labels().list(userId="me").execute()
            labels = labels_response.get("labels", [])

            label_id = None
            for label in labels:
                if label["name"] == label_name:
                    label_id = label["id"]
                    break

            if not label_id:
                # Create the label
                label = (
                    self.service.users()
                    .labels()
                    .create(userId="me", body={"name": label_name})
                    .execute()
                )
                label_id = label["id"]

            # Add label to message
            self.service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"addLabelIds": [label_id]},
            ).execute()
            return True

        except HttpError as e:
            logger.error(f"Error adding label: {e}")
            return False
