# mcp.bolster.online

[![🧪 Tests & Coverage](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/test-and-coverage.yml/badge.svg)](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/test-and-coverage.yml)
[![🔍 Code Quality](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/code-quality.yml/badge.svg)](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/code-quality.yml)
[![🎮 Fun Experiments](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/fun-experiments.yml/badge.svg)](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/fun-experiments.yml)
[![🤖 AI Content Review](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/ai-content-review.yml/badge.svg)](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/ai-content-review.yml)
[![codecov](https://codecov.io/gh/andrewbolster/mcp.bolster.online/branch/main/graph/badge.svg)](https://codecov.io/gh/andrewbolster/mcp.bolster.online)

[![Python](https://img.shields.io/badge/Python-3.11%20|%203.12%20|%203.13-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastMCP](https://img.shields.io/badge/Framework-FastMCP-purple?logo=lightning&logoColor=white)](https://gofastmcp.com/)
[![Ruff](https://img.shields.io/badge/Code%20Quality-Ruff-red?logo=ruff&logoColor=white)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/badge/Package%20Manager-uv-green?logo=python&logoColor=white)](https://github.com/astral-sh/uv)
[![License](https://img.shields.io/badge/License-GPL--3.0-red?logo=gnu&logoColor=white)](LICENSE)

[![ARM64 Support](https://img.shields.io/badge/ARM64-Supported-brightgreen?logo=arm&logoColor=white)](https://github.com/andrewbolster/mcp.bolster.online/actions/workflows/test-and-coverage.yml)
[![Pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://pre-commit.com/)

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
- **Multi-Platform Support** - Ubuntu (x64/ARM64), Python 3.11-3.13
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

## Deployment

### nginx + Webhook Deployment

This section covers deploying the MCP server on a Linux server using nginx as a reverse proxy and GitHub webhooks for automatic updates.

#### 1. Server Setup

**Install Dependencies:**
```bash
sudo apt update
sudo apt install nginx python3 python3-pip git
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

#### 2. Create Systemd Service

Create `/etc/systemd/system/mcp-bolster.service`:
```ini
[Unit]
Description=MCP Bolster Online Server
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/mcp.bolster.online
Environment=PATH=/opt/mcp.bolster.online/.venv/bin
ExecStart=/opt/mcp.bolster.online/.venv/bin/python app.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

**Enable and Start Service:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable mcp-bolster
sudo systemctl start mcp-bolster
sudo systemctl status mcp-bolster
```

#### 3. nginx Configuration

Create `/etc/nginx/sites-available/mcp.bolster.online`:
```nginx
server {
    listen 80;
    server_name mcp.bolster.online;

    # MCP Server (if it serves HTTP)
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Webhook endpoint
    location /webhook {
        proxy_pass http://localhost:9000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**Enable Site:**
```bash
sudo ln -s /etc/nginx/sites-available/mcp.bolster.online /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

#### 4. GitHub Webhook Setup

**Install webhook listener:**
```bash
sudo apt install webhook
# Or compile from source for latest version
```

**Create webhook configuration** `/opt/mcp.bolster.online/webhook.json`:
```json
[
  {
    "id": "mcp-bolster-deploy",
    "execute-command": "/opt/mcp.bolster.online/deploy.sh",
    "command-working-directory": "/opt/mcp.bolster.online",
    "http-methods": ["POST"],
    "match": [
      {
        "type": "payload-hash-sha256",
        "secret": "YOUR_WEBHOOK_SECRET",
        "parameter": {
          "source": "header",
          "name": "X-Hub-Signature-256"
        }
      },
      {
        "type": "value",
        "value": "refs/heads/main",
        "parameter": {
          "source": "payload",
          "name": "ref"
        }
      }
    ]
  }
]
```

**Create deployment script** `/opt/mcp.bolster.online/deploy.sh`:
```bash
#!/bin/bash
set -e

cd /opt/mcp.bolster.online

# Pull latest changes
git pull origin main

# Update dependencies
uv sync

# Run tests
uv run pytest test_app.py

# Restart service if tests pass
sudo systemctl restart mcp-bolster

# Log deployment
echo "$(date): Deployment successful" >> /var/log/mcp-bolster-deploy.log
```

**Make script executable:**
```bash
chmod +x /opt/mcp.bolster.online/deploy.sh
```

**Create webhook systemd service** `/etc/systemd/system/mcp-webhook.service`:
```ini
[Unit]
Description=MCP Bolster Webhook Listener
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
ExecStart=/usr/bin/webhook -hooks /opt/mcp.bolster.online/webhook.json -verbose -port 9000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

**Start webhook service:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable mcp-webhook
sudo systemctl start mcp-webhook
```

#### 5. GitHub Repository Setup

1. Go to your repository settings → Webhooks
2. Add webhook:
   - **Payload URL**: `http://mcp.bolster.online/webhook`
   - **Content type**: `application/json`
   - **Secret**: Same as in `webhook.json`
   - **Events**: Just push events
   - **Active**: ✓

#### 6. SSL/HTTPS Setup (Optional)

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d mcp.bolster.online
```

#### 7. Monitoring

**Check service status:**
```bash
sudo systemctl status mcp-bolster
sudo systemctl status mcp-webhook
sudo journalctl -u mcp-bolster -f
```

**Check logs:**
```bash
tail -f /var/log/mcp-bolster-deploy.log
sudo journalctl -u mcp-webhook -f
```

#### Security Considerations

- Use webhook secrets to verify GitHub requests
- Run services with limited user permissions (www-data)
- Implement fail-safe deployment (rollback on test failures)
- Monitor deployment logs for security issues
- Keep server and dependencies updated

This setup provides automatic deployment triggered by GitHub pushes to the main branch, with nginx serving as a reverse proxy for both the MCP server and webhook listener.
