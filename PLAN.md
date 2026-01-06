# Influencer Negotiation Automation System - Implementation Plan

## Executive Summary

Build an AI-powered system that automates influencer outreach and negotiation via email, with human-in-the-loop approval through Slack. The system will handle routine negotiations, follow-ups, and Q&A while escalating decisions to the marketing manager for approval.

---

## 1. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         INFLUENCER AUTOMATION SYSTEM                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐             │
│  │   Gmail API  │────▶│  Email       │────▶│   Claude     │             │
│  │  (Incoming)  │     │  Processor   │     │   Engine     │             │
│  └──────────────┘     └──────────────┘     └──────────────┘             │
│                              │                    │                       │
│                              ▼                    ▼                       │
│                       ┌──────────────┐     ┌──────────────┐             │
│                       │   Database   │◀───▶│  Response    │             │
│                       │  (State &    │     │  Generator   │             │
│                       │   History)   │     └──────────────┘             │
│                       └──────────────┘            │                       │
│                              │                    ▼                       │
│  ┌──────────────┐           │            ┌──────────────┐              │
│  │   Gmail API  │◀──────────┼────────────│   Approval   │              │
│  │  (Outgoing)  │           │            │   Queue      │              │
│  └──────────────┘           │            └──────────────┘              │
│                              │                    │                       │
│                              ▼                    ▼                       │
│                       ┌──────────────┐     ┌──────────────┐             │
│                       │  Scheduler   │     │  Slack Bot   │             │
│                       │  (Follow-ups)│     │  (Approvals) │             │
│                       └──────────────┘     └──────────────┘             │
│                                                                           │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Core Components

### 2.1 Email Processor
- **Purpose**: Monitors Gmail inbox for influencer responses
- **Technology**: Gmail API with OAuth 2.0
- **Features**:
  - Real-time or polling-based email monitoring
  - Thread tracking (group emails by conversation)
  - Sender identification and matching to known influencers
  - Attachment handling (for content submissions)

### 2.2 Claude Engine
- **Purpose**: Understands email context and generates appropriate responses
- **Technology**: Claude API (Anthropic)
- **Features**:
  - Classify email intent (question, negotiation, acceptance, rejection, content submission)
  - Generate contextually appropriate responses
  - Apply negotiation rules and boundaries
  - Determine if human escalation is needed

### 2.3 Database / State Management
- **Purpose**: Track all influencer interactions and states
- **Technology**: SQLite (simple) or PostgreSQL (scalable)
- **Key Entities**:
  - Influencers (contact info, status, history)
  - Conversations (email threads, current state)
  - Pending approvals
  - Negotiation history (offers, counteroffers)
  - Configuration (pricing rules, templates)

### 2.4 Approval Queue + Slack Bot
- **Purpose**: Human-in-the-loop approval workflow
- **Technology**: Slack API (Bot + Interactive Messages)
- **Features**:
  - Batch daily/periodic summaries
  - Show drafted responses for review
  - One-click approve/reject/edit
  - Urgent escalations for edge cases

### 2.5 Scheduler
- **Purpose**: Automated follow-ups and batch processing
- **Technology**: APScheduler or Celery
- **Features**:
  - Follow-up reminders after X days of no response
  - Daily summary generation
  - Stale conversation cleanup

---

## 3. Influencer Lifecycle & States

```
┌─────────────┐
│   SOURCED   │ ← Initial state when influencer is added
└──────┬──────┘
       │ (Initial outreach sent)
       ▼
┌─────────────┐
│  CONTACTED  │ ← Waiting for first response
└──────┬──────┘
       │ (Response received)
       ▼
┌─────────────┐
│ NEGOTIATING │ ← Active back-and-forth
└──────┬──────┘
       │
       ├──────────────┬──────────────┐
       ▼              ▼              ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│   AGREED    │ │  DECLINED   │ │   STALE     │
└──────┬──────┘ └─────────────┘ └─────────────┘
       │
       ▼
┌─────────────┐
│  CONTENT    │ ← Waiting for content delivery
│  PENDING    │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  CONTENT    │ ← Content received, needs review
│  RECEIVED   │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  COMPLETED  │ ← Deal finished
└─────────────┘
```

---

## 4. Configuration & Rules Engine

### 4.1 Pricing Rules (config/pricing.yaml)
```yaml
pricing:
  base_rates:
    nano: { min: 50, max: 150, followers: "1K-10K" }
    micro: { min: 150, max: 500, followers: "10K-50K" }
    mid: { min: 500, max: 2000, followers: "50K-500K" }
    macro: { min: 2000, max: 10000, followers: "500K-1M" }
    mega: { min: 10000, max: 50000, followers: "1M+" }

  negotiation:
    max_increase_percent: 20  # Max we'll go above initial offer
    auto_approve_under: 500   # Auto-approve deals under this amount
    escalate_over: 5000       # Always escalate deals over this amount

  content_types:
    instagram_reel: 1.0       # Multiplier
    instagram_story: 0.5
    tiktok_video: 1.2
    youtube_short: 1.5
    youtube_video: 3.0
```

### 4.2 Response Templates (config/templates.yaml)
```yaml
templates:
  initial_outreach:
    subject: "Collaboration Opportunity with [BRAND]"
    body: |
      Hi {influencer_name},

      We love your content and would like to discuss a paid collaboration...

  negotiation_counter:
    body: |
      Thank you for your interest! We appreciate your rate of {their_rate}.
      Based on our campaign budget, we can offer {our_counter}...

  follow_up:
    body: |
      Hi {influencer_name},

      Just following up on our previous conversation...
```

### 4.3 Negotiation Rules (config/rules.yaml)
```yaml
rules:
  auto_responses:
    - trigger: "asking about timeline"
      response_type: "timeline_info"
    - trigger: "asking about content format"
      response_type: "format_requirements"
    - trigger: "price increase <= 10%"
      action: "counter_with_midpoint"
    - trigger: "price increase > 20%"
      action: "escalate_to_human"

  escalation_triggers:
    - "exclusive deal request"
    - "contract modifications"
    - "usage rights beyond social"
    - "rate more than 30% above budget"

  follow_up_schedule:
    first_follow_up_days: 3
    second_follow_up_days: 7
    mark_stale_days: 14
```

---

## 5. Data Models

### 5.1 Core Tables

```sql
-- Influencers
CREATE TABLE influencers (
    id UUID PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    platform VARCHAR(50),  -- instagram, tiktok, youtube
    handle VARCHAR(255),
    follower_count INTEGER,
    tier VARCHAR(20),  -- nano, micro, mid, macro, mega
    status VARCHAR(50) DEFAULT 'sourced',
    initial_rate_offered DECIMAL(10,2),
    agreed_rate DECIMAL(10,2),
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Email Threads
CREATE TABLE conversations (
    id UUID PRIMARY KEY,
    influencer_id UUID REFERENCES influencers(id),
    gmail_thread_id VARCHAR(255) UNIQUE,
    subject VARCHAR(500),
    status VARCHAR(50),  -- active, pending_approval, completed
    last_message_at TIMESTAMP,
    last_message_from VARCHAR(50),  -- 'us' or 'them'
    next_follow_up_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Individual Emails
CREATE TABLE emails (
    id UUID PRIMARY KEY,
    conversation_id UUID REFERENCES conversations(id),
    gmail_message_id VARCHAR(255) UNIQUE,
    direction VARCHAR(10),  -- inbound, outbound
    from_email VARCHAR(255),
    subject VARCHAR(500),
    body TEXT,
    intent_classification VARCHAR(100),
    sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Pending Approvals
CREATE TABLE pending_approvals (
    id UUID PRIMARY KEY,
    conversation_id UUID REFERENCES conversations(id),
    draft_response TEXT,
    response_type VARCHAR(100),
    summary TEXT,
    status VARCHAR(50) DEFAULT 'pending',  -- pending, approved, rejected, edited
    slack_message_ts VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    reviewed_at TIMESTAMP
);

-- Negotiation History
CREATE TABLE negotiation_events (
    id UUID PRIMARY KEY,
    conversation_id UUID REFERENCES conversations(id),
    event_type VARCHAR(50),  -- offer, counter, accept, reject
    our_amount DECIMAL(10,2),
    their_amount DECIMAL(10,2),
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 6. Slack Integration Design

### 6.1 Daily Summary Message
```
📊 *Daily Influencer Summary* - Jan 6, 2026

*New Responses (5)*
• @sarah_creates (45K followers) - Interested, asking about timeline
• @mike_vlogs (120K followers) - Counter-offered $800 (we offered $600)
• @lifestyle_lisa (30K followers) - Accepted our offer of $300!
• @techreview_tom (200K followers) - Asking about content format
• @fitness_fiona (80K followers) - Declined, budget too low

*Pending Follow-ups (3)*
• @travel_adventures - No response in 5 days
• @foodie_adventures - No response in 3 days
• @style_maven - No response in 4 days

*Drafted Responses Ready for Approval*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 6.2 Individual Approval Cards
```
┌────────────────────────────────────────────────┐
│ 📧 Response to @mike_vlogs                     │
├────────────────────────────────────────────────┤
│ *Their message:*                               │
│ "Thanks for reaching out! I usually charge     │
│ $800 for this type of content..."              │
│                                                │
│ *Drafted response:*                            │
│ "Hi Mike! We appreciate your interest and      │
│ understand your rates. We can meet you at      │
│ $700, which is the maximum for this campaign...│
│                                                │
│ [✅ Approve] [✏️ Edit] [❌ Reject] [👀 View Full]│
└────────────────────────────────────────────────┘
```

---

## 7. Project Structure

```
influencer-automation/
├── config/
│   ├── pricing.yaml          # Pricing tiers and rules
│   ├── templates.yaml        # Email templates
│   ├── rules.yaml            # Negotiation rules
│   └── settings.yaml         # App settings (API keys, etc.)
│
├── src/
│   ├── __init__.py
│   ├── main.py               # Application entry point
│   │
│   ├── email/
│   │   ├── __init__.py
│   │   ├── gmail_client.py   # Gmail API wrapper
│   │   ├── processor.py      # Email processing logic
│   │   └── sender.py         # Email sending logic
│   │
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── claude_client.py  # Claude API wrapper
│   │   ├── classifier.py     # Intent classification
│   │   └── responder.py      # Response generation
│   │
│   ├── slack/
│   │   ├── __init__.py
│   │   ├── bot.py            # Slack bot setup
│   │   ├── messages.py       # Message formatting
│   │   └── handlers.py       # Button/interaction handlers
│   │
│   ├── database/
│   │   ├── __init__.py
│   │   ├── models.py         # SQLAlchemy models
│   │   ├── repository.py     # Data access layer
│   │   └── migrations/       # Database migrations
│   │
│   ├── scheduler/
│   │   ├── __init__.py
│   │   ├── jobs.py           # Scheduled job definitions
│   │   └── follow_ups.py     # Follow-up logic
│   │
│   └── utils/
│       ├── __init__.py
│       ├── config.py         # Config loader
│       └── logging.py        # Logging setup
│
├── tests/
│   ├── __init__.py
│   ├── test_email_processor.py
│   ├── test_classifier.py
│   ├── test_responder.py
│   └── test_slack_handlers.py
│
├── scripts/
│   ├── setup_gmail_oauth.py  # OAuth setup helper
│   └── seed_influencers.py   # Import influencers
│
├── requirements.txt
├── docker-compose.yaml       # Local dev environment
├── Dockerfile
└── README.md
```

---

## 8. Implementation Phases

### Phase 1: Foundation (Core Infrastructure)
1. Set up project structure and dependencies
2. Implement Gmail OAuth flow and basic email reading
3. Create database models and migrations
4. Build basic Claude integration for email classification
5. Create simple CLI for testing

**Deliverable**: Can read emails and classify their intent

### Phase 2: Response Generation
1. Implement response template system
2. Build Claude-powered response generator
3. Create negotiation logic (counters, boundaries)
4. Add approval queue system
5. Basic email sending capability

**Deliverable**: Can generate appropriate draft responses

### Phase 3: Slack Integration
1. Set up Slack bot with OAuth
2. Build summary message formatting
3. Implement interactive approval buttons
4. Add edit/reject functionality
5. Connect approval flow to email sending

**Deliverable**: Full approval workflow via Slack

### Phase 4: Automation & Polish
1. Implement scheduler for follow-ups
2. Add follow-up email generation
3. Build daily summary reports
4. Add conversation state tracking
5. Error handling and logging

**Deliverable**: Fully automated system with follow-ups

### Phase 5: Production Readiness
1. Add comprehensive tests
2. Create Docker deployment
3. Add monitoring and alerting
4. Documentation
5. Security review

**Deliverable**: Production-ready system

---

## 9. Technology Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Language | Python 3.11+ | Great ecosystem for APIs and AI |
| Email | Gmail API | Native integration with user's account |
| AI | Claude API (Anthropic) | Superior reasoning for negotiations |
| Database | PostgreSQL | Reliable, scalable |
| ORM | SQLAlchemy | Pythonic database access |
| Slack | Slack Bolt SDK | Official SDK, handles OAuth well |
| Scheduler | APScheduler | Simple, reliable for our needs |
| Config | Pydantic + YAML | Type-safe configuration |
| HTTP | httpx | Modern async HTTP client |
| Containerization | Docker | Easy deployment |

---

## 10. Security Considerations

1. **OAuth Tokens**: Store Gmail/Slack tokens encrypted at rest
2. **API Keys**: Use environment variables, never commit
3. **Email Content**: PII considerations - log minimally
4. **Access Control**: Only marketing manager can approve
5. **Audit Trail**: Log all actions for compliance

---

## 11. Open Questions / Decisions Needed

1. **Approval Frequency**: Real-time approvals vs. daily batches?
2. **Auto-approve Threshold**: What deal size can be auto-approved?
3. **Escalation Criteria**: What situations always need human input?
4. **Content Handling**: How should submitted content be processed?
5. **Multi-user Support**: Just one user for now, or plan for team?
6. **Hosting**: Cloud provider preference? (AWS, GCP, etc.)

---

## 12. Success Metrics

- **Time Saved**: Reduce email handling time by 80%
- **Response Time**: Average response to influencers < 4 hours
- **Deal Closure Rate**: Track conversion from contact to agreement
- **Error Rate**: < 1% of responses need major corrections

---

## Next Steps

Ready to begin **Phase 1** implementation. I'll start with:
1. Project scaffolding
2. Gmail API integration
3. Database setup
4. Basic Claude classification

Want me to proceed?
