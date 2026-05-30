#!/bin/bash
set -e

# Deployment script for MCP Bolster Online
# This script is triggered by GitHub webhooks for automatic deployments

DEPLOYMENT_DIR="/opt/mcp.bolster.online"
SERVICE_NAME="mcp-bolster"
LOG_FILE="/var/log/mcp-bolster-deploy.log"

# Redirect all output to the log file immediately. This detaches us from the
# webhook's stdout pipe, so when the webhook service restarts mid-deployment
# (to reload its config) there's no SIGPIPE killing us or our child processes.
exec 1>>"$LOG_FILE" 2>&1

# Function to log messages
log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S'): $1"
}

# Function to handle errors
handle_error() {
    log_message "ERROR: Deployment failed at step: $1"
    # Optionally restart the previous version
    sudo systemctl start "$SERVICE_NAME" || true
    exit 1
}

log_message "Starting deployment process"

cd "$DEPLOYMENT_DIR" || handle_error "Change to deployment directory"

# Stop the service before deployment
log_message "Stopping MCP service"
sudo systemctl stop "$SERVICE_NAME" || handle_error "Stop service"

# Pull latest changes
log_message "Pulling latest changes from GitHub"
git fetch origin main || handle_error "Git fetch"
git reset --hard origin/main || handle_error "Git reset"

# Re-inject webhook secret (git reset reverts webhook.json to its placeholder)
if [ -n "${WEBHOOK_SECRET}" ]; then
    sed -i 's|$WEBHOOK_SECRET|'"${WEBHOOK_SECRET}"'|g' deployment/webhook.json
    log_message "Webhook secret injected into config"
    # Reload webhook service so it picks up the re-injected config
    # (hotreload stops watching after git reset replaces the file)
    sudo systemctl restart mcp-webhook || log_message "WARNING: webhook restart failed"
else
    log_message "WARNING: WEBHOOK_SECRET not set, skipping secret injection"
fi

# Redirect all cache dirs to writable location (ProtectSystem=strict makes /var/www/.cache read-only)
export XDG_CACHE_HOME="/opt/mcp.bolster.online/.cache"
export UV_CACHE_DIR="/opt/mcp.bolster.online/.cache/uv"
export PRE_COMMIT_HOME="/opt/mcp.bolster.online/.cache/pre-commit"

# Update dependencies
log_message "Updating dependencies"
UV_CMD=$(which uv 2>/dev/null || echo "/usr/local/bin/uv")
$UV_CMD sync || handle_error "Dependency update"

# Run pre-commit checks
log_message "Running code quality checks"
$UV_CMD run pre-commit run --all-files || log_message "WARNING: Pre-commit checks had issues"

# Run tests to ensure deployment is safe
log_message "Running test suite"
$UV_CMD run pytest test_app.py --cov=app -v || handle_error "Tests failed"

# Run security scans
log_message "Running security scans"
$UV_CMD add --group dev bandit safety || true
$UV_CMD run bandit -r app.py || log_message "WARNING: Bandit security scan had warnings"
$UV_CMD run safety check || log_message "WARNING: Safety vulnerability check had warnings"

# Validate configuration
log_message "Validating MCP server configuration"
timeout 15s $UV_CMD run python -c "
import app
print('✅ MCP server configuration is valid')
print(f'✅ Server name: {app.mcp.name}')
print(f'✅ Tools: {[t for t in dir(app) if callable(getattr(app, t, None)) and not t.startswith(\"_\")]}')
" || handle_error "Configuration validation"

# Start the service
log_message "Starting MCP service"
sudo systemctl start "$SERVICE_NAME" || handle_error "Start service"

# Wait a moment and check service status
sleep 2
if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    log_message "✅ Deployment successful - service is running"
else
    handle_error "Service failed to start after deployment"
fi

# Log deployment success with commit info
COMMIT_HASH=$(git rev-parse HEAD)
COMMIT_MSG=$(git log -1 --pretty=format:"%s")
log_message "🚀 Deployment completed successfully"
log_message "📝 Commit: $COMMIT_HASH - $COMMIT_MSG"

# Optional: Send notification (uncomment and configure as needed)
# curl -X POST "https://api.github.com/repos/andrewbolster/mcp.bolster.online/issues" \
#   -H "Authorization: token $GITHUB_TOKEN" \
#   -d "{\"title\":\"✅ Deployment Success\",\"body\":\"Deployment completed at $(date)\\n\\nCommit: $COMMIT_HASH\\n$COMMIT_MSG\"}"

log_message "Deployment process completed"
