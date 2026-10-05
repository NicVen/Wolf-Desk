#!/usr/bin/env bash
# STAALWAG auto-ship — run by autoship.timer every 5 minutes (as root).
#
# Ships whatever has been merged into the live branch, with no SSH needed:
#   1. fetch the branch; stop if nothing new
#   2. pull it, install new requirements if they changed
#   3. compile-check the Python, restart the services
#   4. health-check both services; if either is down, roll back to the
#      previous commit, restart, and Telegram the owner
#   (step 3 also runs tests/ — checkout, payment, activation — before restarting)
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

envval() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"'"'"''; }

tg() {
    local tok chat
    tok=$(envval UPDATES_BOT_TOKEN); chat=$(envval UPDATES_CHAT)
    if [ -z "$tok" ] || [ -z "$chat" ]; then   # no updates channel: licensing bot -> admin chat
        tok=$(envval LICENSE_BOT_TOKEN); chat=$(envval LICENSE_ADMIN_CHAT)
    fi
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

restart_all() {
    systemctl restart $SERVICES
    # Markov bot (deploy/markov-setup.sh): restarted only if it is installed and running.
    systemctl try-restart markov-bot 2>/dev/null || true
    # Guardian MT5 watcher (deploy/guardian-setup.sh): same.
    systemctl try-restart guardian-watch 2>/dev/null || true
}

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
if command -v node >/dev/null && [ -d "$REPO/markov/node_modules" ]; then
    if ! git_app diff --quiet "$OLD" "$NEW" -- markov/package-lock.json; then
        as_app sh -c "cd '$REPO/markov' && npm ci --omit=dev --silent" || fail "installing Markov bot packages"
    fi
    as_app sh -c "cd '$REPO/markov' && node --check server.js && timeout 120 node --test" >/dev/null 2>&1 \
        || fail "Markov bot tests failed"
fi
as_app "$REPO/.venv/bin/python" -m compileall -q "$REPO/serve.py" "$REPO/licensing" "$REPO/compiler" >/dev/null \
    || fail "code doesn't compile"
# Money-path tests (checkout -> payment -> activation) on a throwaway DB, before
# anything restarts. A failure rolls back before the new code ever runs.
if [ -d "$REPO/tests" ]; then
    as_app sh -c "cd '$REPO' && timeout 300 .venv/bin/python -m unittest discover -s tests -q" >/dev/null 2>&1 \
        || fail "payment tests failed"
fi
restart_all
healthy || fail "app didn't come back up"

rm -f "$STATE/bad"
# Weekly builds tag their commits "Ideas-Built: 3, 7" / "Bugs-Fixed: 2". Once
# live, mark them on the Ideas board (voters get "you asked, we built it").
ADMIN=$(envval ADMIN_TOKEN)
mark() {   # mark <status> <ids...>
    local st=$1 id; shift
    for id in "$@"; do
        curl -s -m 10 -X POST http://127.0.0.1:8790/admin/suggestion -H "X-Admin-Token: $ADMIN" \
            -H "Content-Type: application/json" -d "{\"id\": $id, \"status\": \"$st\"}" >/dev/null || true
    done
}
if [ -n "$ADMIN" ]; then
    BODY=$(git_app log --format=%B "$OLD..$NEW")
    mark built $(echo "$BODY" | sed -n 's/^Ideas-Built:[[:space:]]*//p' | tr -c '0-9\n' ' ')
    mark done  $(echo "$BODY" | sed -n 's/^Bugs-Fixed:[[:space:]]*//p'  | tr -c '0-9\n' ' ')
fi
MSG=$(git_app log -1 --format=%s "$NEW")
log "live: $MSG"
# Success is only announced in the dedicated updates channel (confirms an
# approval landed); without that channel it stays quiet.
if [ -n "$(envval UPDATES_CHAT)" ] && [ -n "$(envval UPDATES_BOT_TOKEN)" ]; then
    tg "✅ Live in the app: $MSG"
fi
