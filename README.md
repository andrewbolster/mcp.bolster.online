# mcp.bolster.online

[![🧪 Tests & Coverage](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/test-and-coverage.yml/badge.svg?branch=main)](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/test-and-coverage.yml)
[![🔍 Code Quality](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/code-quality.yml/badge.svg?branch=main)](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/code-quality.yml)
[![🎮 Fun Experiments](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/fun-experiments.yml/badge.svg?branch=main)](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/fun-experiments.yml)
[![🤖 AI Content Review](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/ai-content-review.yml/badge.svg?branch=main)](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/ai-content-review.yml)
[![codecov](https://codecov.io/gh/andrewbolster/mcp.bolster.online/branch/main/graph/badge.svg)](https://codecov.io/gh/andrewbolster/mcp.bolster.online)

![Python](https://img.shields.io/pypi/pyversions/mcp-bolster-online?style=for-the-badge)
[![FastMCP](https://img.shields.io/badge/Framework-FastMCP-purple?logo=lightning&logoColor=white&style=for-the-badge)](https://gofastmcp.com/)
[![Ruff](https://img.shields.io/badge/Code%20Quality-Ruff-red?logo=ruff&logoColor=white&style=for-the-badge)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/badge/Package%20Manager-uv-green?logo=python&logoColor=white&style=for-the-badge)](https://github.com/astral-sh/uv)
[![License](https://img.shields.io/badge/License-GPL--3.0-red?logo=gnu&logoColor=white&style=for-the-badge)](LICENSE)

[![codecov](https://img.shields.io/codecov/c/github/andrewbolster/mcp.bolster.online?style=for-the-badge&logo=codecov)](https://codecov.io/gh/andrewbolster/mcp.bolster.online)
[![Multi-Platform](https://img.shields.io/badge/Ubuntu-Latest%20%7C%2022.04-orange?logo=ubuntu&logoColor=white&style=for-the-badge)](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/test-and-coverage.yml)
[![Pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white&style=for-the-badge)](https://pre-commit.com/)
[![Deployment](https://img.shields.io/badge/Deployment-Ready-success?logo=docker&logoColor=white&style=for-the-badge)](https://github.com/andrewbolster/mcp.bolster.online/tree/main/deployment)

An MCP (Model Context Protocol) server providing curated resources and tools about Andrew Bolster, including professional background, research interests, community involvement, and contact/availability tools.

## 🚀 Features

### MCP Resources

- **Personal Website** - Main website and technical blog
- **Professional Profile** - Current roles and expertise
- **Farset Labs** - Belfast hackerspace co-founder information
- **Social Media** - Professional networking profiles
- **Research Interests** - Academic and technical focus areas
- **Community Involvement** - Organizational roles and activities
- **Technical Blog** - Writing and thought leadership

### MCP Tools

- **Contact Tool** - Send professional inquiries (placeholder implementation)
- **Availability Tool** - Merged free/busy across multiple private calendars, with two response tiers: full detail (which calendar, event title) for Andrew, authenticated via `/auth/mcp`; free/busy-only for everyone else, including anonymous callers on the public `/mcp` endpoint
- **Blog Posts Tool** - Fetch recent posts from RSS feed
- **Page Content Tool** - Fetch the full text of one page (blog post or static page) as markdown (andrewbolster.info only)

### Development Features

- **FastMCP Framework** - Modern MCP server development
- **92% Test Coverage** - Comprehensive test suite with pytest
- **Multi-Platform Support** - Ubuntu Latest & 22.04, Python 3.11-3.13
- **Modern Code Quality** - Ruff formatting/linting, mypy type checking
- **Pre-commit Hooks** - Automated code quality checks
- **GitHub Actions** - CI/CD with AI-powered content validation

## Development

### Prerequisites

- Python 3.11+
- uv (package manager)

### Setup

```bash
git clone https://github.com/andrewbolster/mcp.bolster.online.git
cd mcp.bolster.online
uv sync
```

### Running Tests

```bash
# Run tests with coverage
uv run pytest test_app.py --cov=app --cov-report=term-missing -v

# Run all quality checks (same as CI)
uv run ruff check .          # Linting
uv run ruff format --check . # Format checking
uv run mypy app.py --ignore-missing-imports  # Type checking
```

### Running the Server

```bash
uv run python app.py
```

### Pre-commit Setup

```bash
# Install pre-commit hooks (automatic code quality)
uv run pre-commit install

# Run pre-commit on all files
uv run pre-commit run --all-files
```

## 🔐 Configuration & Secrets

None of this server's secrets live in this repository — not in a `.env` file, not in `deployment/`, not anywhere git-tracked. Every value below is an **environment variable**, set on the production host via a systemd drop-in override (`sudo systemctl edit mcp-bolster`, which writes to `/etc/systemd/system/mcp-bolster.service.d/override.conf` — a file outside this repo, untouched by `git reset --hard` on every deploy). `deployment/systemd/mcp-bolster.service` intentionally has no `Environment=` lines for any of these, for the same reason: whatever's tracked in git is, by definition, not a place to put a secret.

This also follows from how the service is sandboxed (`ProtectHome=true`, `ProtectSystem=strict`, `ReadWritePaths=/opt/mcp.bolster.online` only, `HOME=/opt/mcp.bolster.online`) — the process can't read a config file under a real user's home directory even if you wanted it to, so environment variables are the only mechanism these secrets *can* use, not just the preferred one.

| Variable | Purpose | Required |
|---|---|---|
| `GITHUB_CLIENT_ID` | GitHub OAuth App client ID, backs the `/auth/mcp` login flow | Yes, for `/auth/mcp` |
| `GITHUB_CLIENT_SECRET` | GitHub OAuth App client secret | Yes, for `/auth/mcp` |
| `GITHUB_ALLOWED_LOGINS` | Comma-separated GitHub usernames allowed to authenticate at all. Empty/unset fails closed (nobody can log in), not open | Yes, for `/auth/mcp` |
| `CALENDARS_CONFIG_JSON_B64` | Base64-encoded calendar feeds for the availability tool (see below) | No — tool degrades to "not configured" without it |

### Setting a secret in production

```bash
sudo systemctl edit mcp-bolster
```

This opens an editor for the override file. Add the variables you need under `[Service]`:

```ini
[Service]
Environment=GITHUB_CLIENT_ID=your-client-id
Environment=GITHUB_CLIENT_SECRET=your-client-secret
Environment=GITHUB_ALLOWED_LOGINS=andrewbolster
Environment=CALENDARS_CONFIG_JSON_B64=eyJjYWxlbmRhcnMiOiBb...
```

Then apply it:

```bash
sudo systemctl daemon-reload
sudo systemctl restart mcp-bolster
```

`systemctl edit` is the point of this whole approach: the override file lives under `/etc/systemd/system/`, is never part of the git checkout at `/opt/mcp.bolster.online`, and survives every `git reset --hard` the deploy script does. Nobody needs to remember not to commit it — it structurally can't be, because it's never inside the repository in the first place.

### `CALENDARS_CONFIG_JSON_B64` schema

**This one has to be base64, not raw JSON — and it's not optional polish.** systemd's `Environment=` directive applies shell-like quote parsing to its values: it strips any `"` character it finds *anywhere* in the string, not just at the edges, and separately treats `%` as the start of a specifier (`%h`, `%H`, etc. — real Google Calendar URLs contain literal `%40`). Both silently corrupt a raw JSON value — no error, no warning in the unit file, just a stripped-down invalid string reaching the process (or the whole `Environment=` line silently dropped if a `%`-specifier fails to resolve). Base64's alphabet contains neither character, so it passes through untouched. Generate it with:

```bash
python3 -c 'import json,base64; print(base64.b64encode(json.dumps({
  "calendars": [
    {"name": "work", "url": "https://outlook.office365.com/owa/calendar/REDACTED/calendar.ics"},
    {"name": "personal", "url": "https://calendar.google.com/calendar/ical/REDACTED/private-REDACTED/basic.ics"}
  ]
}).encode()).decode())'
```

The decoded JSON shape:

```json
{
  "calendars": [
    {"name": "work", "url": "https://outlook.office365.com/owa/calendar/REDACTED/calendar.ics"},
    {"name": "personal", "url": "https://calendar.google.com/calendar/ical/REDACTED/private-REDACTED/basic.ics"}
  ]
}
```

- `name` is a free-text label. It's shown to the calendar owner (Andrew, authenticated) alongside each busy block, and never shown to anyone else — so it can be anything meaningful to you, it doesn't need to hide anything.
- `url` is the private/secret ICS feed URL for that calendar (Google's "Secret address in iCal format", Outlook's private calendar sharing link, etc.). Anyone with this URL can read the calendar directly, so treat it exactly like a password — this is the actual secret, not the JSON structure around it.
- The tool never echoes these URLs back in any response, to either the owner or anonymous callers — only computed busy/tentative time ranges (plus, for the owner, the `name` label and event titles) ever leave the server.
- Missing, non-base64, or base64-that-doesn't-decode-to-valid-JSON doesn't crash the server; `check_availability` just reports that availability checking isn't configured.

### Local development

For local testing, export the same variable in your own shell before running the server — never in a file this repo's `.gitignore` would need to know about, because there isn't one. Plain shell `export` doesn't have systemd's quote-stripping problem, but base64 is still the one supported format (keeping local and production identical is worth more than saving one encode step):

```bash
export CALENDARS_CONFIG_JSON_B64=$(python3 -c 'import json,base64; print(base64.b64encode(json.dumps({"calendars":[{"name":"test","url":"https://..."}]}).encode()).decode())')
uv run python app.py
```

If you'd rather not have real calendar URLs sitting in your shell history, source them from a file kept outside any repository (e.g. `~/.config/bolster/mcp-env.sh`, `chmod 600`) instead of typing `export` interactively:

```bash
# ~/.config/bolster/mcp-env.sh — not tracked anywhere, chmod 600
export CALENDARS_CONFIG_JSON_B64=eyJjYWxlbmRhcnMiOiBb...
```

```bash
source ~/.config/bolster/mcp-env.sh
uv run python app.py
```

## 🚀 Deployment

### nginx + Webhook Deployment

This section covers deploying the MCP server on a Linux server using nginx as a reverse proxy and GitHub webhooks for automatic updates. All configuration files are maintained in this repository for easy version control and updates.

#### 1. Server Setup

**Install Dependencies:**

```bash
sudo apt update
sudo apt install nginx python3 python3-pip git webhook
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Create Deployment Directory:**

```bash
sudo mkdir -p /opt/mcp.bolster.online
sudo chown $USER:$USER /opt/mcp.bolster.online
```

**Clone Repository:**

```bash
cd /opt
git clone https://github.com/andrewbolster/mcp.bolster.online.git
cd mcp.bolster.online
uv sync
```

#### 2. Configure System Services (using symlinks)

All configuration files are maintained in the repository under `deployment/`. Use symlinks to connect them to system locations:

**Create systemd services:**

```bash
# Link service files from repository
sudo ln -sf /opt/mcp.bolster.online/deployment/systemd/mcp-bolster.service /etc/systemd/system/
sudo ln -sf /opt/mcp.bolster.online/deployment/systemd/mcp-webhook.service /etc/systemd/system/

# Enable and start services
sudo systemctl daemon-reload
sudo systemctl enable mcp-bolster mcp-webhook
sudo systemctl start mcp-bolster mcp-webhook
sudo systemctl status mcp-bolster mcp-webhook
```

**Configure nginx:**

```bash
# Link nginx configuration from repository
sudo ln -sf /opt/mcp.bolster.online/deployment/nginx/mcp.bolster.online /etc/nginx/sites-available/
sudo ln -sf /etc/nginx/sites-available/mcp.bolster.online /etc/nginx/sites-enabled/

# Test and reload nginx
sudo nginx -t
sudo systemctl reload nginx
```

#### 3. Customize Webhook Configuration

**Edit webhook secret:**

```bash
# Edit the webhook configuration file
nano /opt/mcp.bolster.online/deployment/webhook.json
# Replace "YOUR_WEBHOOK_SECRET_HERE" with your actual secret
```

**Restart webhook service after changes:**

```bash
sudo systemctl restart mcp-webhook
```

#### 4. GitHub Repository Setup

1. Go to repository settings → Webhooks
1. Add webhook:
   - **Payload URL**: `http://mcp.bolster.online/webhook`
   - **Content type**: `application/json`
   - **Secret**: Same as configured in `deployment/webhook.json`
   - **Events**: Just push events
   - **Active**: ✓

#### 5. SSL/HTTPS Setup (Recommended)

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d mcp.bolster.online
```

#### 6. Deployment Features

The deployment setup includes several advanced features:

**Automatic Deployment Pipeline:**

- ✅ Pulls latest code from `main` branch
- ✅ Updates dependencies with `uv sync`
- ✅ Runs full test suite before deployment
- ✅ Performs security scans (Bandit, Safety)
- ✅ Validates MCP server configuration
- ✅ Zero-downtime restart with rollback on failure
- ✅ Comprehensive logging with timestamps
- ✅ Skip deployment with `[skip deploy]` in commit message

**Security Features:**

- 🔒 GitHub IP allowlist for webhook endpoint
- 🔒 Rate limiting on webhook endpoint (5 requests/minute)
- 🔒 Webhook signature verification
- 🔒 Services run as `www-data` with limited permissions
- 🔒 System protection with `ProtectSystem=strict`
- 🔒 Resource limits (CPU, Memory, File descriptors)
- 🔒 Security headers and sensitive file blocking

**Monitoring & Maintenance:**

- 📊 Structured logging to systemd journal
- 📊 Deployment logs in `/var/log/mcp-bolster-deploy.log`
- 📊 Health check endpoint at `/health`
- 📊 Automatic service restart on failure
- 📊 Hot-reload webhook configuration

#### 7. Monitoring Commands

**Check service status:**

```bash
sudo systemctl status mcp-bolster mcp-webhook
sudo journalctl -u mcp-bolster -f
sudo journalctl -u mcp-webhook -f
```

**Check deployment logs:**

```bash
tail -f /var/log/mcp-bolster-deploy.log
```

**Test deployment:**

```bash
# Manual deployment trigger (for testing)
sudo /opt/mcp.bolster.online/deployment/deploy.sh
```

**Check configuration:**

```bash
# Test nginx configuration
sudo nginx -t

# Validate webhook configuration
webhook -hooks /opt/mcp.bolster.online/deployment/webhook.json -verbose -dry-run
```

#### 8. Updating Configuration

Since all configuration files are in the repository, updates are automatic:

1. **Update configuration files** in the `deployment/` directory
1. **Commit and push** changes to GitHub
1. **Services automatically restart** with new configuration via symlinks
1. **For immediate updates** without waiting for webhook:
   ```bash
   cd /opt/mcp.bolster.online
   git pull origin main
   sudo systemctl daemon-reload  # If systemd files changed
   sudo systemctl restart mcp-bolster mcp-webhook
   sudo systemctl reload nginx   # If nginx config changed
   ```

This approach provides version-controlled infrastructure with automatic deployments, comprehensive security, and easy maintenance.
