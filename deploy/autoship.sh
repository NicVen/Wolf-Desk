#!/usr/bin/env bash
# STAALWAG auto-ship — run by autoship.timer every 5 minutes (as root).
#
# Ships whatever has been merged into the live branch, with no SSH needed:
#   1. fetch the branch; stop if nothing new
#   2. pull it, install new requirements if they changed
#   3. compile-check the Python, restart the services
#   4. health-check both services; if either is down, roll back to the
#      previous commit, restart, and Telegram the owner
# A commit that was rolled back is remembered and never retried, so a bad merge
# can't loop. Merging a fix on top ships normally.
set -u

REPO=/opt/wolf-desk
APP_USER=wolf
SERVICES="wolf-desk staalwag-licensing"
STATE=/var/lib/staalwag-autoship
ENV_FILE=/etc/staalwag-licensing.env      # reuses the licensing bot for alerts

mkdir -p "$STATE"
log() { echo "[autoship] $*"; }
as_app() { runuser -u "$APP_USER" -- "$@"; }
git_app() { as_app git -C "$REPO" "$@"; }

tg() {
    local tok chat
    tok=$(grep -E '^LICENSE_BOT_TOKEN=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"'"'"'')
    chat=$(grep -E '^LICENSE_ADMIN_CHAT=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"'"'"'')
    [ -n "$tok" ] && [ -n "$chat" ] || { log "no Telegram configured: $1"; return 0; }
    curl -s -m 15 "https://api.telegram.org/bot$tok/sendMessage" \
        --data-urlencode "chat_id=$chat" --data-urlencode "text=[STAALWAG auto-ship] $1" \
        -d disable_web_page_preview=true >/dev/null || true
}

healthy() {
    local i
    for i in 1 2 3 4 5 6 7 8 9 10; do
        if curl -sf -m 5 http://127.0.0.1:8777/appversion >/dev/null &&
           curl -sf -m 5 http://127.0.0.1:8790/health >/dev/null; then
            return 0
        fi
        sleep 3
    done
    return 1
}

restart_all() { systemctl restart $SERVICES; }

BRANCH=$(git_app rev-parse --abbrev-ref HEAD) || { log "not a git checkout"; exit 1; }
git_app fetch -q origin "$BRANCH" || { log "fetch failed (network?)"; exit 0; }
OLD=$(git_app rev-parse HEAD)
NEW=$(git_app rev-parse "origin/$BRANCH")
[ "$OLD" = "$NEW" ] && exit 0
if [ "$(cat "$STATE/bad" 2>/dev/null)" = "$NEW" ]; then
    exit 0   # already rolled this one back; wait for a fix to be merged
fi

log "shipping $BRANCH ${OLD:0:7} -> ${NEW:0:7}"
if ! git_app merge -q --ff-only "origin/$BRANCH"; then
    echo "$NEW" > "$STATE/bad"
    tg "⚠️ Couldn't update: the server copy has local changes or the branch was rewritten. Nothing changed; the app is still on ${OLD:0:7}."
    exit 1
fi

fail() {
    log "FAILED: $1 — rolling back to ${OLD:0:7}"
    git_app reset -q --hard "$OLD"
    restart_all
    echo "$NEW" > "$STATE/bad"
    if healthy; then
        tg "❌ Update ${NEW:0:7} failed ($1). Rolled back automatically; the app is running the previous version."
    else
        tg "🚨 Update ${NEW:0:7} failed ($1) AND the rollback isn't answering. Please check the server."
    fi
    exit 1
}

if git_app diff --quiet "$OLD" "$NEW" -- requirements.txt; then :; else
    as_app "$REPO/.venv/bin/pip" install -q -r "$REPO/requirements.txt" || fail "installing requirements"
fi
as_app "$REPO/.venv/bin/python" -m compileall -q "$REPO/serve.py" "$REPO/licensing" "$REPO/compiler" >/dev/null \
    || fail "code doesn't compile"
restart_all
healthy || fail "app didn't come back up"

rm -f "$STATE/bad"
log "live: $(git_app log -1 --format=%s "$NEW")"   # success stays quiet; only problems message the owner
