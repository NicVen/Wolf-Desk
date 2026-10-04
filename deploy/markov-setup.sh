#!/usr/bin/env bash
# One-time: run the Markov 18-pair bot on this server (replaces the old Railway /
# PC copy). Run on the VPS:
#   cd /opt/wolf-desk && sudo -u wolf git pull && sudo bash deploy/markov-setup.sh
#
# It asks for the bot token and finds the channel for you: add the bot to the
# (private test) channel as an admin and post any message there first.
# After this, auto-ship keeps it updated like the rest of the app.
set -u
REPO=/opt/wolf-desk
ENV=/etc/markov-bot.env
DATA=/var/lib/markov-bot
die() { echo "ERROR: $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run with sudo"

# 1. Node 18+ (Ubuntu's own nodejs package is too old)
major=$(node -v 2>/dev/null | sed 's/^v\([0-9]*\).*/\1/')
if [ -z "$major" ] || [ "$major" -lt 18 ]; then
    echo "Installing Node.js 20..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null || die "Node.js repo setup failed"
    apt-get install -y nodejs >/dev/null || die "Node.js install failed"
fi
echo "Node $(node -v)"

# 2. Dependencies
runuser -u wolf -- sh -c "cd $REPO/markov && npm ci --omit=dev --silent" || die "npm install failed"
mkdir -p "$DATA" && chown wolf:wolf "$DATA"

# 3. Settings (kept if they already exist)
if [ ! -f "$ENV" ]; then
    read -r -p "Paste the Markov bot's Telegram token: " TOKEN
    [ -n "$TOKEN" ] || die "no token"
    # A webhook left over from Railway blocks getUpdates; the bot doesn't need it.
    curl -s "https://api.telegram.org/bot$TOKEN/deleteWebhook" >/dev/null
    echo "Channels/groups this bot has seen (post a message in the channel first):"
    curl -s "https://api.telegram.org/bot$TOKEN/getUpdates" | python3 -c '
import json, sys
seen = {}
for u in json.load(sys.stdin).get("result", []):
    for k in ("channel_post", "message", "my_chat_member"):
        c = (u.get(k) or {}).get("chat")
        if c: seen[c["id"]] = c.get("title") or c.get("username") or c.get("first_name")
for i, t in seen.items(): print("   %s   %s" % (i, t))
if not seen: print("   (none yet - add the bot as admin, post a message, run this again)")'
    read -r -p "Paste the channel id from the list (starts with -100): " CHAT
    [ -n "$CHAT" ] || die "no channel id"
    cat > "$ENV" <<CONF
TELEGRAM_BOT_TOKEN=$TOKEN
TELEGRAM_CHAT_ID=$CHAT
PORT=8783
SIGNALS_FILE=$DATA/signals-store.json
BOOK_FILE=$DATA/open-calls.json
# Paper test: every post is labelled. Set false only after 30 calls at PF >= 1.3.
PAPER_TEST=true
START_ACTIVE=true
CONF
    chmod 600 "$ENV"
fi

# 4. Service
cp "$REPO/deploy/markov-bot.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now markov-bot || die "service failed to start"
sleep 4
echo -n "markov-bot: "; systemctl is-active markov-bot
curl -s -m 5 http://127.0.0.1:8783/health; echo
echo
echo "Done. Results: https://staalwag.com/markov/signals.json"
echo "Make sure the old copy (PC or Railway) is OFF so calls aren't posted twice."
