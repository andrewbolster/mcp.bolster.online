# mcp.bolster.online

[![🧪 Tests & Coverage](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/test-and-coverage.yml/badge.svg?branch=main)](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/test-and-coverage.yml)
[![🔍 Code Quality](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/code-quality.yml/badge.svg?branch=main)](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/code-quality.yml)
[![🎮 Fun Experiments](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/fun-experiments.yml/badge.svg?branch=main)](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/fun-experiments.yml)
[![🤖 AI Content Review](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/ai-content-review.yml/badge.svg?branch=main)](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/ai-content-review.yml)
[![codecov](https://codecov.io/gh/andrewbolster/mcp.bolster.online/branch/main/graph/badge.svg)](https://codecov.io/gh/andrewbolster/mcp.bolster.online)

[![Python](https://img.shields.io/badge/Python-3.11%20|%203.12%20|%203.13-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastMCP](https://img.shields.io/badge/Framework-FastMCP-purple?logo=lightning&logoColor=white)](https://gofastmcp.com/)
[![Ruff](https://img.shields.io/badge/Code%20Quality-Ruff-red?logo=ruff&logoColor=white)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/badge/Package%20Manager-uv-green?logo=python&logoColor=white)](https://github.com/astral-sh/uv)
[![License](https://img.shields.io/badge/License-GPL--3.0-red?logo=gnu&logoColor=white)](LICENSE)

[![Test Coverage](https://img.shields.io/badge/Coverage-92%25-brightgreen?logo=codecov&logoColor=white)](https://codecov.io/gh/andrewbolster/mcp.bolster.online)
[![Multi-Platform](https://img.shields.io/badge/Ubuntu-Latest%20%7C%2022.04-orange?logo=ubuntu&logoColor=white)](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/test-and-coverage.yml)
[![Pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://pre-commit.com/)
[![Deployment](https://img.shields.io/badge/Deployment-Ready-success?logo=docker&logoColor=white)](https://github.com/andrewbolster/mcp.bolster.online/tree/main/deployment)

An MCP (Model Context Protocol) server providing curated resources and tools about Andrew Bolster, including professional background, research interests, community involvement, and contact/availability tools.

## 🚀 Features

### MCP Resources (7 available)
- **Personal Website** - Main website and technical blog
- **Professional Profile** - Current roles and expertise
- **Farset Labs** - Belfast hackerspace co-founder information
- **Social Media** - Professional networking profiles
- **Research Interests** - Academic and technical focus areas
- **Community Involvement** - Organizational roles and activities
- **Technical Blog** - Writing and thought leadership

### MCP Tools (2 available)
- **Contact Tool** - Send professional inquiries (placeholder implementation)
- **Availability Tool** - Check calendar availability via public iCal feed

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
2. Add webhook:
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
2. **Commit and push** changes to GitHub
3. **Services automatically restart** with new configuration via symlinks
4. **For immediate updates** without waiting for webhook:
   ```bash
   cd /opt/mcp.bolster.online
   git pull origin main
   sudo systemctl daemon-reload  # If systemd files changed
   sudo systemctl restart mcp-bolster mcp-webhook
   sudo systemctl reload nginx   # If nginx config changed
   ```

This approach provides version-controlled infrastructure with automatic deployments, comprehensive security, and easy maintenance.
