#!/usr/bin/env bash
# One-time: connect the private "STAALWAG Updates" Telegram channel through its
# OWN bot (separate from the signal bots and the licensing bot).
# Before running: make a bot with @BotFather, create the channel, add that bot
# as an admin, and post "hi" in the channel. Then on the VPS:
#   cd /opt/wolf-desk && sudo -u wolf git pull && sudo bash deploy/updates-channel-setup.sh
# It asks for the bot token here on the server (never paste it in a chat).
set -e
ENV_FILE=/etc/staalwag-licensing.env

envval() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"'"'"''; }
set_var() {   # set_var NAME VALUE  (replace or append in the env file)
    if grep -qE "^$1=" "$ENV_FILE"; then sed -i "s|^$1=.*|$1=$2|" "$ENV_FILE"; else echo "$1=$2" >> "$ENV_FILE"; fi
}
botname() {   # prints @username if the token is valid
    curl -s "https://api.telegram.org/bot$1/getMe" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print("@" + d["result"]["username"] if d.get("ok") else "")' 2>/dev/null
}

TOK=$(envval UPDATES_BOT_TOKEN)
NAME=""
[ -n "$TOK" ] && NAME=$(botname "$TOK")
while [ -z "$NAME" ]; do
    echo
    read -r -p "Paste the token @BotFather gave you (looks like 123456:ABC...) and press Enter: " TOK
    TOK=$(echo "$TOK" | tr -d '[:space:]')
    NAME=$(botname "$TOK")
    [ -n "$NAME" ] || echo "That token didn't work. Copy it again from @BotFather (the whole line) and retry."
done
set_var UPDATES_BOT_TOKEN "$TOK"
echo "Using bot $NAME"

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
    echo "Couldn't see the channel yet. Make sure $NAME is an ADMIN of the channel, post 'hi' in it, then run this again."
    exit 1
fi
CHAT=${FOUND%%|*}; TITLE=${FOUND#*|}

set_var UPDATES_CHAT "$CHAT"
if [ -z "$(envval DIGEST_TOKEN)" ]; then
    set_var DIGEST_TOKEN "$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
fi
chmod 600 "$ENV_FILE"
systemctl restart staalwag-licensing

curl -s "https://api.telegram.org/bot$TOK/sendMessage" --data-urlencode "chat_id=$CHAT" \
    --data-urlencode "text=✅ Connected. Weekly app updates and Approve buttons will arrive here." >/dev/null

echo
echo "Connected to channel: $TITLE (via $NAME)"
echo
echo "Last step: copy this whole line into your Claude project's cloud environment"
echo "(Environment variables box):"
echo
echo "DIGEST_TOKEN=$(envval DIGEST_TOKEN)"
echo
