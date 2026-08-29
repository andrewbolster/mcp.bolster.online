# Deployment Configuration

This directory contains all the configuration files needed to deploy the MCP Bolster Online server using nginx and systemd. All files are version-controlled and deployed using symlinks for easy maintenance.

## Directory Structure

```
deployment/
├── deploy.sh                    # Automated deployment script (triggered by webhooks)
├── webhook.json                 # GitHub webhook configuration
├── nginx/
│   └── mcp.bolster.online      # nginx virtual host configuration
├── systemd/
│   ├── mcp-bolster.service     # Main MCP server systemd service
│   └── mcp-webhook.service     # Webhook listener systemd service
└── README.md                   # This file
```

## File Descriptions

### `deploy.sh`
- **Purpose**: Automated deployment script triggered by GitHub webhooks
- **Features**:
  - Safe deployment with rollback on failure
  - Full test suite execution before deployment
  - Security scanning (Bandit, Safety)
  - Configuration validation
  - Comprehensive logging
- **Location**: Executed from `/opt/mcp.bolster.online/deployment/deploy.sh`
- **Permissions**: Must be executable (`chmod +x`)

### `webhook.json`
- **Purpose**: Configuration for the webhook listener service
- **Features**:
  - GitHub SHA-256 signature verification (X-Hub-Signature-256)
  - Branch filtering (only `main` branch)
  - Skip deployment with `[skip deploy]` in commit message
  - Rate limiting and security controls
- **Security**: Uses `$WEBHOOK_SECRET` environment variable reference (2025 best practice)
- **Deployment**: Set `WEBHOOK_SECRET` environment variable on server before starting webhook service
- **Location**: Referenced by webhook service at `/opt/mcp.bolster.online/deployment/webhook.json`

### `nginx/mcp.bolster.online`
- **Purpose**: nginx virtual host configuration
- **Features**:
  - Reverse proxy for MCP server (port 9001)
  - Webhook endpoint routing (port 9000)
  - Security headers and rate limiting
  - GitHub IP allowlist for webhook endpoint
  - Health check endpoint
  - SSL/TLS ready configuration
- **Deployment**: Symlinked to `/etc/nginx/sites-available/mcp.bolster.online`

### `systemd/mcp-bolster.service`
- **Purpose**: Main MCP server systemd service
- **Features**:
  - Runs as `www-data` user for security
  - Automatic restart on failure
  - Resource limits (512MB RAM, 200% CPU)
  - Security hardening (`ProtectSystem=strict`)
  - Proper Python virtual environment handling
- **Deployment**: Symlinked to `/etc/systemd/system/mcp-bolster.service`

### `systemd/mcp-webhook.service`
- **Purpose**: GitHub webhook listener systemd service
- **Features**:
  - Lightweight resource usage (128MB RAM, 50% CPU)
  - Hot-reload webhook configuration
  - Security hardening
  - Integration with main deployment script
- **Deployment**: Symlinked to `/etc/systemd/system/mcp-webhook.service`

## Deployment Process

1. **Initial Setup**: Clone repository to `/opt/mcp.bolster.online`
2. **Symlink Creation**: Create symlinks from system locations to repository files
3. **Service Configuration**: Enable and start systemd services
4. **Webhook Setup**: Configure GitHub webhook with matching secret
5. **SSL Setup**: Configure SSL certificates with certbot (recommended)

## Expected Drift on the Production Host

`/opt/mcp.bolster.online` is a live git checkout owned by `www-data`, sitting on
`main`. `git status` there is **never clean**, and most of that is by design. Check
findings against this table before treating anything as an incident.

Because the checkout is owned by `www-data`, git refuses to run as another user
("dubious ownership"). Inspect without mutating global config:

```bash
git -c safe.directory=/opt/mcp.bolster.online -C /opt/mcp.bolster.online status
```

| Path | State | Why |
| --- | --- | --- |
| `deployment/webhook.json` | always modified | `deploy.sh` runs `git reset --hard origin/main`, which restores the `$WEBHOOK_SECRET` placeholder, then `sed`-injects the real secret back. The file is dirty from the moment a deploy finishes. **Never commit this diff.** |
| `pyproject.toml`, `uv.lock` | modified | `bandit` and `safety` were added to dev deps on the host so `deploy.sh`'s security scan step could run. Not committed upstream, so every `git reset --hard` drops them. Fixing this means committing both to `[dependency-groups] dev`. |
| `.venv/`, `.cache/`, `__pycache__/`, `.pytest_cache/`, `.coverage`, `.safety/` | untracked | `deploy.sh` builds the venv and runs the full test suite in place. Expected. |
| `.local/` | untracked | `HOME=/opt/mcp.bolster.online` in the service unit, so tooling scribbles here. Harmless. |
| `deployment/deploy.sh.bak` | untracked | Stale hand-edit backup predating the current `deploy.sh`. Safe to delete. |

### Config linkage

Most system config is symlinked back into this repo, so editing a file here and
deploying updates the live system. Two exceptions matter:

| System path | Linkage |
| --- | --- |
| `/etc/nginx/sites-available/mcp.bolster.online` | symlink → `deployment/nginx/mcp.bolster.online` |
| `/etc/systemd/system/mcp-bolster.service` | symlink → `deployment/systemd/mcp-bolster.service` |
| `/etc/systemd/system/mcp-webhook.service` | **copy**, not a symlink — currently byte-identical, but repo edits will not propagate |
| `/etc/systemd/system/mcp-bolster.service.d/auth.conf` | host-only drop-in holding the GitHub OAuth client ID/secret and `GITHUB_ALLOWED_LOGINS`. Deliberately absent from the repo. |

### Verifying the deployment is current

```bash
git -c safe.directory=/opt/mcp.bolster.online -C /opt/mcp.bolster.online \
    rev-parse HEAD                      # should equal origin/main
systemctl is-active mcp-bolster mcp-webhook
ss -tlnp | grep -E ':9000|:9001'        # 9001 = MCP (localhost only), 9000 = webhook
```

A local clone that has not fetched will make the deployed SHA look unknown or
divergent. Always `git fetch origin` before comparing.

## Security Features

- **Process Isolation**: Services run as `www-data` with limited permissions
- **Resource Limits**: CPU, memory, and file descriptor limits
- **Network Security**: GitHub IP allowlist, rate limiting, SHA-256 signature verification
- **System Hardening**: `ProtectSystem=strict`, `NoNewPrivileges=true`
- **Secure Headers**: X-Frame-Options, X-Content-Type-Options, etc.
- **File Protection**: Block access to sensitive files (`.env`, `.log`, etc.)
- **Secret Management**: Environment variable references (no hardcoded secrets)
- **Pre-commit Security**: GitGuardian secret scanning, Bandit vulnerability checks
- **Git History Protection**: Secrets removed from all git history using filter-branch

## Maintenance

### Updating Configuration
Since all files are in the repository:
1. Edit files in the `deployment/` directory
2. Commit and push changes
3. Configuration automatically updates via symlinks
4. Restart affected services if needed

### Monitoring
```bash
# Service status
sudo systemctl status mcp-bolster mcp-webhook

# Live logs
sudo journalctl -u mcp-bolster -f
sudo journalctl -u mcp-webhook -f

# Deployment logs
tail -f /var/log/mcp-bolster-deploy.log

# Test configuration
sudo nginx -t
webhook -hooks deployment/webhook.json -verbose -dry-run
```

### Manual Deployment
```bash
# Test deployment script
sudo /opt/mcp.bolster.online/deployment/deploy.sh

# Restart services
sudo systemctl restart mcp-bolster mcp-webhook
sudo systemctl reload nginx
```

## Troubleshooting

### Common Issues
1. **Permission Errors**: Ensure `www-data` can read repository files
2. **Webhook Secret Mismatch**: Verify `WEBHOOK_SECRET` environment variable matches GitHub webhook secret
3. **Environment Variable Missing**: Ensure `WEBHOOK_SECRET` is set before starting webhook service
4. **Port Conflicts**: Ensure ports 9001 and 9000 are available
5. **SSL Certificate**: Use certbot for HTTPS setup

### Environment Variable Setup
```bash
# Set the webhook secret environment variable
export WEBHOOK_SECRET="your-github-webhook-secret-here"

# For systemd services, add to service file or environment file
# /etc/systemd/system/mcp-webhook.service.d/environment.conf:
# Environment=WEBHOOK_SECRET=your-github-webhook-secret-here
```

### Log Locations
- **nginx**: `/var/log/nginx/mcp.bolster.online.access.log`
- **Deployment**: `/var/log/mcp-bolster-deploy.log`
- **Services**: `sudo journalctl -u mcp-bolster` / `sudo journalctl -u mcp-webhook`

This setup provides enterprise-grade deployment with version control, security, and automated operations.
