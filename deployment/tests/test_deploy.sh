#!/bin/bash
# Offline harness for deployment/deploy.sh: runs it against a temporary bare remote with sudo, systemctl,
# nginx, curl and uv shimmed via PATH. Touches nothing outside its own temp directory.
# Usage: deployment/tests/test_deploy.sh
# shellcheck disable=SC2317  # helpers are invoked indirectly through check()
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/../deploy.sh"
TMP="$(mktemp -d)"
FAILS=0

mkdir -p "$TMP/bin"
cat > "$TMP/bin/sudo" <<'SH'
#!/bin/bash
exec "$@"
SH
cat > "$TMP/bin/systemctl" <<'SH'
#!/bin/bash
echo "systemctl $*" >> "$SHIM_CALLS"
case "$1" in
    is-active) cat "$SHIM_STATE" ;;
    stop) echo inactive > "$SHIM_STATE" ;;
    start)
        if [ -e "$DEPLOYMENT_DIR/breaks_start" ]; then exit 1; fi
        echo active > "$SHIM_STATE" ;;
esac
exit 0
SH
cat > "$TMP/bin/nginx" <<'SH'
#!/bin/bash
echo "nginx $*" >> "$SHIM_CALLS"
SH
cat > "$TMP/bin/curl" <<'SH'
#!/bin/bash
echo "curl $*" >> "$SHIM_CALLS"
if [ -e "$DEPLOYMENT_DIR/breaks_health" ]; then printf '000'; exit 7; fi
printf '404'
SH
cat > "$TMP/bin/uv" <<'SH'
#!/bin/bash
echo "uv $PWD :: $*" >> "$SHIM_CALLS"
if [ "$1" = run ] && [ "$2" = pytest ] && [ -e "$PWD/breaks_tests" ]; then echo "1 failed"; exit 1; fi
if [ "$1" = run ] && [ "$2" = --with ] && [ "$3" = safety ]; then echo "10 vulnerabilities were reported"; fi
if [ "${SHIM_UV_SLEEP:-0}" != 0 ] && [ "$1" = run ] && [ "$2" = pytest ]; then sleep "$SHIM_UV_SLEEP"; fi
exit 0
SH
chmod +x "$TMP/bin/"*

new_env() { # $1 = scenario name; sets up remote, live checkout and shim state
    S="$TMP/$1"
    mkdir -p "$S"
    git init -q --bare --initial-branch=main "$S/remote.git"
    git clone -q "$S/remote.git" "$S/seed" 2>/dev/null
    (
        cd "$S/seed" || exit 1
        git checkout -q -b main
        mkdir -p deployment
        # shellcheck disable=SC2016  # literal placeholder, as in the real webhook.json
        echo '{"secret":"$WEBHOOK_SECRET"}' > deployment/webhook.json
        echo v1 > VERSION
        git add -A
        git -c user.name=t -c user.email=t@t commit -qm v1
        git push -q origin main
    )
    git clone -q "$S/remote.git" "$S/live"
    export DEPLOYMENT_DIR="$S/live" LOG_FILE="$S/deploy.log" SHIM_CALLS="$S/calls" SHIM_STATE="$S/state"
    export WEBHOOK_SECRET=s3cret HEALTH_TRIES=2 HEALTH_INTERVAL=0 START_GRACE=0 LOCK_WAIT=30
    export UV_CMD="$TMP/bin/uv"
    : > "$SHIM_CALLS"
    echo active > "$SHIM_STATE"
    V1=$(git -C "$S/live" rev-parse HEAD)
}

push_commit() { # $1 = marker file to add (optional)
    (
        cd "$S/seed" || exit 1
        echo "$RANDOM" >> VERSION
        if [ -n "${1:-}" ]; then touch "$1"; fi
        git add -A
        git -c user.name=t -c user.email=t@t commit -qm next
        git push -q origin main
    )
    V2=$(git -C "$S/seed" rev-parse HEAD)
}

check() { # $1 = description, rest = test command
    local d="$1"
    shift
    if "$@"; then echo "  PASS: $d"; else echo "  FAIL: $d"; FAILS=$((FAILS + 1)); fi
}
called() { grep -q -- "$1" "$SHIM_CALLS"; }
not_called() { ! grep -q -- "$1" "$SHIM_CALLS"; }
head_is() { [ "$(git -C "$DEPLOYMENT_DIR" rev-parse HEAD)" = "$1" ]; }
logged() { grep -q -- "$1" "$LOG_FILE"; }
line_of() { grep -n -- "$1" "$SHIM_CALLS" | head -1 | cut -d: -f1; }
count_of() { grep -c -- "$1" "$SHIM_CALLS"; }
before() { [ "$(line_of "$1")" -lt "$(line_of "$2")" ]; }
run_deploy() { bash "$SCRIPT"; RC=$?; }

export PATH="$TMP/bin:$PATH"

echo "(i) normal deploy"
new_env normal
push_commit
run_deploy
check "exit 0" [ "$RC" -eq 0 ]
check "live checkout at new commit" head_is "$V2"
check "full suite ran in staging" called "run pytest -q"
check "bandit via uv run --with" called "run --with bandit"
check "safety via uv run --with" called "run --with safety"
check "no uv add" not_called "uv .*add"
check "tests ran before the service was stopped" before "run pytest" "systemctl stop"
check "service stopped before started" before "systemctl stop" "systemctl start mcp-bolster"
check "webhook secret injected" grep -q s3cret "$S/live/deployment/webhook.json"
check "nginx tested" called "nginx -t"
check "nginx reloaded" called "systemctl reload nginx"
check "webhook service restarted" called "systemctl restart mcp-webhook"
check "safety summary logged" logged "Safety summary: 10 vulnerabilities"
check "no pre-commit" not_called "pre-commit"
check "staging worktree removed" test -z "$(ls "$S/live/.cache/stage" 2>/dev/null)"
echo "  (re-run with nothing new)"
: > "$SHIM_CALLS"
run_deploy
check "exit 0" [ "$RC" -eq 0 ]
check "logs 'Already deployed'" logged "Already deployed"
check "no stop/start on no-op" not_called "systemctl stop"
check "no tests on no-op" not_called "run pytest"

echo "(ii) failing test in staging"
new_env stagefail
push_commit breaks_tests
run_deploy
check "exit non-zero" [ "$RC" -ne 0 ]
check "service never stopped" not_called "systemctl stop"
check "previous commit still live" head_is "$V1"
check "clear log line" logged "STAGING FAILED at step: test suite"
check "service still active" grep -q '^active' "$SHIM_STATE"

echo "(iii-a) service fails to start after the swap"
new_env startfail
push_commit breaks_start
run_deploy
check "exit non-zero" [ "$RC" -ne 0 ]
check "rolled back to previous commit" head_is "$V1"
check "rollback logged" logged "ROLLING BACK to $V1"
check "start attempted again on old code" test "$(count_of 'systemctl start mcp-bolster')" -ge 2
check "service active after rollback" grep -q '^active' "$SHIM_STATE"

echo "(iii-b) health check fails after the swap"
new_env healthfail
push_commit breaks_health
run_deploy
check "exit non-zero" [ "$RC" -ne 0 ]
check "rolled back to previous commit" head_is "$V1"
check "health failure logged" logged "health check failed after the service was stopped"

echo "(iv) two concurrent invocations"
new_env concurrent
push_commit
export SHIM_UV_SLEEP=3
bash "$SCRIPT" &
P1=$!
sleep 1
bash "$SCRIPT" &
P2=$!
wait "$P1"
R1=$?
wait "$P2"
R2=$?
unset SHIM_UV_SLEEP
check "both exit 0" test "$R1" -eq 0 -a "$R2" -eq 0
check "second waited for the lock" logged "waiting up to"
check "second was a no-op" logged "Already deployed"
check "exactly one stop" test "$(count_of 'systemctl stop')" -eq 1
check "exactly one test run" test "$(count_of 'run pytest')" -eq 1
check "live at new commit" head_is "$V2"

echo
if [ "$FAILS" -eq 0 ]; then echo "ALL PASSED"; else echo "$FAILS CHECK(S) FAILED (logs under $TMP)"; fi
exit "$FAILS"
