# Influencer Negotiation Automation System

An AI-powered system that automates influencer outreach and negotiation via email, with human-in-the-loop approval through Slack.

## Features

- **Automated Email Processing**: Monitors Gmail for influencer responses and classifies them by intent
- **AI-Powered Responses**: Uses Claude to generate contextually appropriate email responses
- **Smart Negotiation**: Configurable pricing rules and negotiation boundaries
- **Slack Approval Workflow**: Batch approvals every 2 hours with one-click approve/reject
- **Automated Follow-ups**: Chase non-responsive influencers after configurable intervals
- **Auto-approve Small Deals**: Deals under $100 are automatically approved

## Architecture

```
Gmail API → Email Processor → Claude Classification → Response Generator
                                                              ↓
                                                    Approval Queue
                                                              ↓
                                                     Slack Bot → Human Approval
                                                              ↓
                                                    Send via Gmail
```

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

Required credentials:
- **Anthropic API Key**: Get from https://console.anthropic.com/
- **Gmail OAuth**: Download `credentials.json` from Google Cloud Console
- **Slack Bot**: Create a Slack app with Bot Token and Signing Secret

### 3. Set Up Gmail OAuth

```bash
python scripts/setup_gmail_oauth.py
```

This will open a browser for Google OAuth authorization.

### 4. Run the System

```bash
# Run as daemon (continuous processing)
python -m src.main --daemon

# Or run individual commands:
python -m src.main --check-emails      # Process new emails once
python -m src.main --send-approvals    # Send approvals to Slack
python -m src.main --status            # View system status
```

## Configuration

### Pricing Rules (`config/pricing.yaml`)

Define pricing tiers based on follower count:
- **Nano** (1K-10K): $50-150
- **Micro** (10K-50K): $150-500
- **Mid** (50K-500K): $500-2000
- **Macro** (500K-1M): $2000-10000
- **Mega** (1M+): $10000-50000

Negotiation settings:
- Auto-approve deals under $100
- Max increase: 20% above initial offer
- Escalate deals over $5000

### Email Templates (`config/templates.yaml`)

Customize email templates for:
- Initial outreach
- Follow-ups (1st and 2nd)
- Counter-offers
- Deal confirmations
- FAQ responses (timeline, format, etc.)

### Automation Rules (`config/rules.yaml`)

Configure:
- Email intent classification
- Escalation triggers (keywords, scenarios)
- Follow-up schedule (3, 7, 14 days)
- Auto-response triggers

## Slack Workflow

Every 2 hours, the system sends a batch of pending approvals to Slack:

```
📧 5 Responses Ready for Approval
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟡 Response to @sarah_creates
   _Negotiation Counter_
   Their ask: $500 → Our counter: $400

   Their message:
   > Thanks for reaching out! My rate is $500...

   Drafted response:
   ```
   Hi Sarah, We appreciate your interest...
   ```

   [✅ Approve] [✏️ Edit] [❌ Reject] [👀 View Full]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[✅ Approve All]
```

## Project Structure

```
├── config/
│   ├── pricing.yaml      # Pricing tiers and rules
│   ├── templates.yaml    # Email templates
│   ├── rules.yaml        # Automation rules
│   └── settings.yaml     # App settings
├── src/
│   ├── ai/               # Claude integration
│   │   ├── classifier.py # Email classification
│   │   └── responder.py  # Response generation
│   ├── database/         # SQLAlchemy models
│   ├── email/            # Gmail API integration
│   ├── scheduler/        # Background jobs
│   ├── slack/            # Slack bot
│   └── main.py           # CLI entry point
├── scripts/
│   ├── setup_gmail_oauth.py
│   └── seed_influencers.py
└── tests/
```

## Importing Influencers

Create a CSV file with influencer data:

```csv
email,name,platform,handle,follower_count,content_type,initial_rate
sarah@example.com,Sarah Creates,instagram,sarah_creates,45000,instagram_reel,
mike@example.com,Mike Vlogs,youtube,mikevlogs,120000,youtube_short,600
```

Import:
```bash
python scripts/seed_influencers.py influencers.csv
```

## Development

Run tests:
```bash
pytest tests/
```

## License

MIT
