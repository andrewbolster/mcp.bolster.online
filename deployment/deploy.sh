#!/bin/bash
# Deployment script for MCP Bolster Online.
# Triggered by GitHub webhooks (the `webhook` service runs it as www-data from deployment/webhook.json).
#
# Flow:
#   1. take an exclusive lock (deploys queue behind each other instead of overlapping);
#   2. fetch origin/main; if that commit is already live and the service is active, do nothing;
#   3. STAGE: check the target commit out into a throwaway worktree and run the full test suite,
#      the security scans and the config validation there. The running service is not touched,
#      so a bad commit is rejected while production keeps serving the previous one;
#   4. SWAP (short downtime): stop, reset to the target, re-inject the webhook secret, reload nginx,
#      `uv sync`, start, then health-check;
#   5. if anything after the stop fails, ROLL BACK to the previous commit and exit non-zero.
#
# Every path and command can be overridden by an environment variable of the same name so that
# deployment/tests/ can exercise this script against a temporary repository. The defaults are the
# production values.

set -uo pipefail

DEPLOYMENT_DIR="${DEPLOYMENT_DIR:-/opt/mcp.bolster.online}"
SERVICE_NAME="${SERVICE_NAME:-mcp-bolster}"
WEBHOOK_SERVICE="${WEBHOOK_SERVICE:-mcp-webhook}"
LOG_FILE="${LOG_FILE:-/var/log/mcp-bolster-deploy.log}"
CACHE_DIR="${DEPLOY_CACHE_DIR:-$DEPLOYMENT_DIR/.cache}"
LOCK_FILE="${LOCK_FILE:-$CACHE_DIR/deploy.lock}"
LOCK_WAIT="${LOCK_WAIT:-600}"
STAGE_ROOT="${STAGE_ROOT:-$CACHE_DIR/stage}"
REMOTE="${DEPLOY_REMOTE:-origin}"
BRANCH="${DEPLOY_BRANCH:-main}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:9001/mcp/}"
HEALTH_TRIES="${HEALTH_TRIES:-12}"
HEALTH_INTERVAL="${HEALTH_INTERVAL:-5}"
START_GRACE="${START_GRACE:-5}"
VALIDATE_TIMEOUT="${VALIDATE_TIMEOUT:-120}"
SUDO="${SUDO:-sudo}"

# Redirect all output to the log file immediately. This detaches us from the
# webhook's stdout pipe, so when the webhook service restarts mid-deployment
# (to reload its config) there's no SIGPIPE killing us or our child processes.
exec 1>>"$LOG_FILE" 2>&1

log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S'): $1"
}

# Redirect all cache dirs to a writable location (ProtectSystem=strict makes /var/www/.cache read-only).
export XDG_CACHE_HOME="$CACHE_DIR"
export UV_CACHE_DIR="$CACHE_DIR/uv"
export PRE_COMMIT_HOME="$CACHE_DIR/pre-commit"

UV_CMD="${UV_CMD:-$(command -v uv 2>/dev/null || echo /usr/local/bin/uv)}"

STAGE_DIR=""
PREV=""
TARGET=""

cleanup_stage() {
    if [ -n "$STAGE_DIR" ] && [ -d "$STAGE_DIR" ]; then
        git -C "$DEPLOYMENT_DIR" worktree remove --force "$STAGE_DIR" >/dev/null 2>&1 || true
    fi
    git -C "$DEPLOYMENT_DIR" worktree prune >/dev/null 2>&1 || true
}
trap cleanup_stage EXIT

# --- 1. Serialise deploys -------------------------------------------------------------------
log_message "Starting deployment process"
mkdir -p "$CACHE_DIR" || { log_message "ERROR: cannot create $CACHE_DIR"; exit 1; }
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log_message "Another deploy is running; waiting up to ${LOCK_WAIT}s for the lock"
    if ! flock -w "$LOCK_WAIT" 9; then
        log_message "ERROR: could not get the deploy lock within ${LOCK_WAIT}s"
        exit 1
    fi
    log_message "Got the deploy lock"
fi

cd "$DEPLOYMENT_DIR" || { log_message "ERROR: cannot change to $DEPLOYMENT_DIR"; exit 1; }

# --- 2. Decide what to deploy ---------------------------------------------------------------
log_message "Fetching $REMOTE/$BRANCH"
if ! git fetch "$REMOTE" "$BRANCH"; then
    log_message "ERROR: git fetch failed; production left untouched"
    exit 1
fi
TARGET=$(git rev-parse "$REMOTE/$BRANCH") || { log_message "ERROR: cannot resolve $REMOTE/$BRANCH"; exit 1; }
PREV=$(git rev-parse HEAD) || { log_message "ERROR: cannot resolve HEAD"; exit 1; }

if [ "$PREV" = "$TARGET" ] && [ "$($SUDO systemctl is-active "$SERVICE_NAME")" = "active" ]; then
    log_message "Already deployed: $TARGET is live and the service is active; nothing to do"
    exit 0
fi
log_message "Deploying $TARGET (currently live: $PREV)"

# --- 3. Stage: test the target before touching the running service --------------------------
stage_failed() {
    log_message "ERROR: STAGING FAILED at step: $1"
    log_message "Production was NOT touched and is still serving $PREV"
    exit 1
}

# Remove staging worktrees left behind by an interrupted earlier run.
git worktree prune
git worktree list --porcelain | awk -v root="$STAGE_ROOT/" '$1 == "worktree" && index($2, root) == 1 { print $2 }' |
    while IFS= read -r old_stage; do
        git worktree remove --force "$old_stage" >/dev/null 2>&1 || true
    done

STAGE_DIR="$STAGE_ROOT/$(date +%Y%m%d-%H%M%S)-${TARGET:0:12}"
log_message "Staging $TARGET in $STAGE_DIR"
mkdir -p "$STAGE_ROOT" || stage_failed "create staging directory"
git worktree add --detach "$STAGE_DIR" "$TARGET" || stage_failed "create staging checkout"

log_message "STAGING: installing dependencies"
(cd "$STAGE_DIR" && "$UV_CMD" sync) || stage_failed "dependency install"

log_message "STAGING: running the full test suite"
(cd "$STAGE_DIR" && "$UV_CMD" run pytest -q) || stage_failed "test suite"

log_message "STAGING: security scans (warnings only)"
(cd "$STAGE_DIR" && "$UV_CMD" run --with bandit bandit -r app.py) ||
    log_message "WARNING: Bandit security scan had warnings"
safety_output=$(cd "$STAGE_DIR" && "$UV_CMD" run --with safety safety check 2>&1)
echo "$safety_output"
safety_count=$(echo "$safety_output" | sed 's/\x1b\[[0-9;]*m//g' |
    grep -oE '[0-9]+ vulnerabilit(y|ies) (was|were) reported' | head -n 1 | grep -oE '^[0-9]+')
log_message "Safety summary: ${safety_count:-unknown} vulnerabilities reported (full output above; warning only)"

log_message "STAGING: validating MCP server configuration (limit ${VALIDATE_TIMEOUT}s)"
(cd "$STAGE_DIR" && timeout "$VALIDATE_TIMEOUT" "$UV_CMD" run python -c "
import app
print('MCP server configuration is valid')
print(f'Server name: {app.mcp.name}')
") || stage_failed "configuration validation"
log_message "Staging passed for $TARGET"

# --- 4. Swap: the only window in which the service is down ----------------------------------
inject_webhook_secret() {
    # git reset reverts webhook.json to its placeholder, so put the secret back.
    if [ -n "${WEBHOOK_SECRET:-}" ]; then
        # shellcheck disable=SC2016  # the single-quoted $WEBHOOK_SECRET is the literal placeholder to replace
        sed -i 's|$WEBHOOK_SECRET|'"${WEBHOOK_SECRET}"'|g' deployment/webhook.json
        log_message "Webhook secret injected into config"
        # Reload the webhook service so it picks up the re-injected config
        # (hotreload stops watching after git reset replaces the file).
        $SUDO systemctl restart "$WEBHOOK_SERVICE" || log_message "WARNING: webhook restart failed"
    else
        log_message "WARNING: WEBHOOK_SECRET not set, skipping secret injection"
    fi
}

reload_nginx() {
    # /etc/nginx/sites-available/mcp.bolster.online is a symlink to deployment/nginx/mcp.bolster.online
    # in this repo, so the reset already updated the file nginx reads; it just needs to re-read it.
    # `nginx -t` validates first, so a bad config leaves the old (working) config running.
    log_message "Reloading nginx configuration"
    if $SUDO nginx -t; then
        $SUDO systemctl reload nginx || log_message "WARNING: nginx reload failed"
    else
        log_message "WARNING: nginx config test failed, skipping reload; old config still active"
    fi
}

health_check() {
    sleep "$START_GRACE"
    if [ "$($SUDO systemctl is-active "$SERVICE_NAME")" != "active" ]; then
        log_message "Health check: service is not active"
        return 1
    fi
    local attempt code
    for attempt in $(seq 1 "$HEALTH_TRIES"); do
        code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$HEALTH_URL" || true)
        case "$code" in
            "" | 000 | 502)
                log_message "Health probe $attempt/$HEALTH_TRIES: no usable response (${code:-none})"
                sleep "$HEALTH_INTERVAL"
                ;;
            *)
                log_message "Health probe: HTTP $code"
                return 0
                ;;
        esac
    done
    log_message "Health check: no usable response from $HEALTH_URL"
    return 1
}

activate_checkout() {
    # Everything that has to follow a `git reset` of the live checkout.
    inject_webhook_secret
    reload_nginx
    log_message "Updating dependencies in the live environment"
    "$UV_CMD" sync
}

rollback() {
    log_message "ERROR: $1 failed after the service was stopped; ROLLING BACK to $PREV"
    if ! git reset --hard "$PREV"; then
        log_message "CRITICAL: rollback could not reset the checkout to $PREV; manual intervention needed"
        exit 2
    fi
    activate_checkout || log_message "WARNING: dependency sync during rollback failed"
    $SUDO systemctl start "$SERVICE_NAME" || log_message "CRITICAL: rollback could not start the service"
    if health_check; then
        log_message "Rollback complete: $PREV is live again"
    else
        log_message "CRITICAL: service unhealthy after rollback to $PREV; manual intervention needed"
    fi
    exit 1
}

log_message "Stopping MCP service"
if ! $SUDO systemctl stop "$SERVICE_NAME"; then
    log_message "ERROR: could not stop the service; nothing was changed, still on $PREV"
    exit 1
fi

log_message "Resetting the live checkout to $TARGET"
git reset --hard "$TARGET" || rollback "git reset"
activate_checkout || rollback "dependency update"

log_message "Starting MCP service"
$SUDO systemctl start "$SERVICE_NAME" || rollback "service start"
health_check || rollback "health check"

# --- 5. Done ---------------------------------------------------------------------------------
log_message "✅ Deployment successful - service is running"
COMMIT_MSG=$(git log -1 --pretty=format:"%s")
log_message "🚀 Deployment completed successfully"
log_message "📝 Commit: $TARGET - $COMMIT_MSG"
log_message "Deployment process completed"
