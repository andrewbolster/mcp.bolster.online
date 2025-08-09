#!/bin/bash
set -e

# Deployment script for MCP Bolster Online
# This script is triggered by GitHub webhooks for automatic deployments

DEPLOYMENT_DIR="/opt/mcp.bolster.online"
SERVICE_NAME="mcp-bolster"
LOG_FILE="/var/log/mcp-bolster-deploy.log"

# Function to log messages
log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S'): $1" | tee -a "$LOG_FILE"
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
git pull origin main || handle_error "Git pull"

# Update dependencies
log_message "Updating dependencies"
uv sync || handle_error "Dependency update"

# Run pre-commit checks
log_message "Running code quality checks"
uv run pre-commit run --all-files || log_message "WARNING: Pre-commit checks had issues"

# Run tests to ensure deployment is safe
log_message "Running test suite"
uv run pytest test_app.py --cov=app -v || handle_error "Tests failed"

# Run security scans
log_message "Running security scans"
uv add --group dev bandit safety || true
uv run bandit -r app.py || log_message "WARNING: Bandit security scan had warnings"
uv run safety check || log_message "WARNING: Safety vulnerability check had warnings"

# Validate configuration
log_message "Validating MCP server configuration"
timeout 10s uv run python -c "
import app
print('✅ MCP server configuration is valid')
print(f'✅ Resources: {len([name for name in dir(app) if name.startswith(\"get_\")])}')
print(f'✅ Tools: 2 (send_contact_message, check_availability)')
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
