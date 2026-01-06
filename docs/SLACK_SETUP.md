# Slack App Setup Guide

This guide walks you through creating a Slack app for the Influencer Automation system.

## Step 1: Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **"Create New App"**
3. Choose **"From scratch"**
4. Enter:
   - App Name: `Influencer Bot` (or whatever you prefer)
   - Workspace: Select your workspace
5. Click **"Create App"**

## Step 2: Enable Socket Mode

Socket Mode allows the bot to receive events without needing a public URL.

1. In your app settings, go to **"Socket Mode"** (left sidebar)
2. Toggle **"Enable Socket Mode"** to ON
3. You'll be prompted to create an App-Level Token:
   - Token Name: `socket-token`
   - Scope: `connections:write`
4. Click **"Generate"**
5. **Copy the token** (starts with `xapp-`) → This is your `SLACK_APP_TOKEN`

## Step 3: Configure Bot Permissions

1. Go to **"OAuth & Permissions"** (left sidebar)
2. Scroll to **"Scopes"** → **"Bot Token Scopes"**
3. Add these scopes:

| Scope | Purpose |
|-------|---------|
| `chat:write` | Send messages |
| `chat:write.public` | Send to channels bot isn't in |
| `commands` | Handle slash commands |
| `app_mentions:read` | Respond to @mentions |
| `im:history` | Read DM history |
| `im:write` | Send DMs |

## Step 4: Install to Workspace

1. Still in **"OAuth & Permissions"**
2. Click **"Install to Workspace"**
3. Review permissions and click **"Allow"**
4. **Copy the Bot User OAuth Token** (starts with `xoxb-`) → This is your `SLACK_BOT_TOKEN`

## Step 5: Get Signing Secret

1. Go to **"Basic Information"** (left sidebar)
2. Scroll to **"App Credentials"**
3. **Copy the Signing Secret** → This is your `SLACK_SIGNING_SECRET`

## Step 6: Create Slash Commands

1. Go to **"Slash Commands"** (left sidebar)
2. Click **"Create New Command"** for each:

### Command 1: /influencer-status
- Command: `/influencer-status`
- Description: `View influencer pipeline status`
- Usage Hint: (leave empty)

### Command 2: /influencer-approvals
- Command: `/influencer-approvals`
- Description: `Show pending response approvals`
- Usage Hint: (leave empty)

### Command 3: /influencer-help
- Command: `/influencer-help`
- Description: `Get help with the influencer bot`
- Usage Hint: (leave empty)

## Step 7: Enable Events (Optional but Recommended)

This allows the bot to respond when mentioned.

1. Go to **"Event Subscriptions"** (left sidebar)
2. Toggle **"Enable Events"** to ON
3. Under **"Subscribe to bot events"**, add:
   - `app_mention`
4. Click **"Save Changes"**

## Step 8: Configure Interactivity

This enables button clicks and modals.

1. Go to **"Interactivity & Shortcuts"** (left sidebar)
2. Toggle **"Interactivity"** to ON
3. No Request URL needed (Socket Mode handles this)
4. Click **"Save Changes"**

## Step 9: Update Your .env File

Add the three tokens to your `.env`:

```bash
SLACK_BOT_TOKEN=xoxb-your-bot-token-here
SLACK_SIGNING_SECRET=your-signing-secret-here
SLACK_APP_TOKEN=xapp-your-app-token-here
```

## Step 10: Create a Channel

1. In Slack, create a channel called `#influencer-updates` (or your preferred name)
2. Invite the bot: `/invite @Influencer Bot`
3. Update `config/settings.yaml` if using a different channel name:
   ```yaml
   slack:
     summary_channel: "#your-channel-name"
   ```

## Step 11: Test the Bot

```bash
# Start the bot
python -m src.main --daemon

# In Slack, try:
/influencer-help
/influencer-status
```

## Troubleshooting

### "not_authed" error
- Check that `SLACK_BOT_TOKEN` starts with `xoxb-`
- Verify the token is correct (no extra spaces)

### "invalid_auth" error
- Regenerate your Bot Token in OAuth & Permissions

### Slash commands not working
- Make sure Socket Mode is enabled
- Verify `SLACK_APP_TOKEN` starts with `xapp-`
- Check that commands are created in Slash Commands

### Buttons not responding
- Ensure Interactivity is enabled
- Socket Mode must be ON

### Bot not responding to mentions
- Add `app_mention` to Event Subscriptions
- Make sure bot is invited to the channel

## App Manifest (Alternative Setup)

If you prefer, you can create the app using this manifest:

```yaml
display_information:
  name: Influencer Bot
  description: Automates influencer outreach and negotiations
features:
  bot_user:
    display_name: Influencer Bot
    always_online: true
  slash_commands:
    - command: /influencer-status
      description: View influencer pipeline status
    - command: /influencer-approvals
      description: Show pending response approvals
    - command: /influencer-help
      description: Get help with the influencer bot
oauth_config:
  scopes:
    bot:
      - chat:write
      - chat:write.public
      - commands
      - app_mentions:read
      - im:history
      - im:write
settings:
  event_subscriptions:
    bot_events:
      - app_mention
  interactivity:
    is_enabled: true
  org_deploy_enabled: false
  socket_mode_enabled: true
```

To use:
1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **"Create New App"** → **"From an app manifest"**
3. Select workspace
4. Paste the YAML above
5. Review and create
6. Then complete Steps 4-5 above to get your tokens
