#!/usr/bin/env python3
"""
Gmail OAuth Setup Helper

This script guides you through setting up Gmail API access.

Prerequisites:
1. Go to Google Cloud Console (https://console.cloud.google.com/)
2. Create a new project (or select an existing one)
3. Enable the Gmail API
4. Create OAuth 2.0 credentials (Desktop application)
5. Download the credentials JSON file

Usage:
    python scripts/setup_gmail_oauth.py
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.email.gmail_client import GmailClient
from src.utils.logging import setup_logging, get_logger


def main():
    setup_logging("INFO")
    logger = get_logger("setup")

    print("\n" + "=" * 60)
    print("Gmail OAuth Setup for Influencer Automation")
    print("=" * 60 + "\n")

    # Check for credentials file
    credentials_file = os.environ.get("GMAIL_CREDENTIALS_FILE", "credentials.json")

    if not os.path.exists(credentials_file):
        print("❌ credentials.json not found!\n")
        print("To set up Gmail API access:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create a new project (or select existing)")
        print("3. Go to 'APIs & Services' > 'Enabled APIs'")
        print("4. Click '+ ENABLE APIS AND SERVICES'")
        print("5. Search for 'Gmail API' and enable it")
        print("6. Go to 'APIs & Services' > 'Credentials'")
        print("7. Click 'Create Credentials' > 'OAuth client ID'")
        print("8. Select 'Desktop application' as the type")
        print("9. Download the JSON file")
        print("10. Rename it to 'credentials.json' and place in project root")
        print()
        sys.exit(1)

    print(f"✓ Found credentials file: {credentials_file}\n")
    print("Starting OAuth flow...")
    print("A browser window will open for you to authorize access.\n")

    client = GmailClient(credentials_file=credentials_file)

    if client.authenticate():
        email = client.get_user_email()
        print("\n" + "=" * 60)
        print(f"✓ Successfully authenticated as: {email}")
        print("=" * 60)
        print("\nYou can now run the automation system!")
        print("  python -m src.main --daemon")
        print()
    else:
        print("\n❌ Authentication failed!")
        print("Please check your credentials and try again.")
        sys.exit(1)


if __name__ == "__main__":
    main()
