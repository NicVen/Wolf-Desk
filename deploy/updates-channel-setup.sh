#!/usr/bin/env bash
# One-time: connect the private "STAALWAG Updates" Telegram channel.
# Before running: create the channel, add your licensing bot as an admin, and
# post any message (e.g. "hi") in the channel. Then on the VPS:
#   cd /opt/wolf-desk && sudo -u wolf git pull && sudo bash deploy/updates-channel-setup.sh
set -e
ENV_FILE=/etc/staalwag-licensing.env
TOK=$(grep -E '^LICENSE_BOT_TOKEN=' "$ENV_FILE" | cut -d= -f2- | tr -d '"'"'"'')
[ -n "$TOK" ] || { echo "LICENSE_BOT_TOKEN is empty in $ENV_FILE"; exit 1; }

FOUND=$(curl -s "https://api.telegram.org/bot$TOK/getUpdates" | python3 -c '
import json, sys
d = json.load(sys.stdin)
chats = {}
for u in d.get("result", []):
    for k in ("channel_post", "my_chat_member"):
        c = (u.get(k) or {}).get("chat") or {}
        if c.get("type") == "channel":
            chats[c["id"]] = c.get("title", "")
if chats:
    cid, title = list(chats.items())[-1]
    print("%s|%s" % (cid, title))
')
if [ -z "$FOUND" ]; then
    echo "Couldn't see the channel yet. Check the bot is an ADMIN of the channel, post 'hi' in it, then run this again."
    exit 1
fi
CHAT=${FOUND%%|*}; TITLE=${FOUND#*|}

set_var() {   # set_var NAME VALUE  (replace or append in the env file)
    if grep -qE "^$1=" "$ENV_FILE"; then sed -i "s|^$1=.*|$1=$2|" "$ENV_FILE"; else echo "$1=$2" >> "$ENV_FILE"; fi
}
set_var UPDATES_CHAT "$CHAT"
if ! grep -qE '^DIGEST_TOKEN=.+' "$ENV_FILE"; then
    set_var DIGEST_TOKEN "$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
fi
chmod 600 "$ENV_FILE"
systemctl restart staalwag-licensing

curl -s "https://api.telegram.org/bot$TOK/sendMessage" --data-urlencode "chat_id=$CHAT" \
    --data-urlencode "text=✅ Connected. Weekly app updates and Approve buttons will arrive here." >/dev/null

DT=$(grep -E '^DIGEST_TOKEN=' "$ENV_FILE" | cut -d= -f2-)
echo
echo "Connected to channel: $TITLE"
echo
echo "Last step: copy this whole line into your Claude project's cloud environment"
echo "(Environment variables box):"
echo
echo "DIGEST_TOKEN=$DT"
echo
