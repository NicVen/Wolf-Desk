#!/usr/bin/env bash
# One-time: link Guardian to an MT5 account (read-only) and start the watcher.
# Run on the VPS:
#   cd /opt/wolf-desk && sudo -u wolf git pull && sudo bash deploy/guardian-setup.sh
#
# Before: sign up free at app.metaapi.cloud and add the MT5 account there with
# its INVESTOR (read-only) password. This script asks for the MetaApi token,
# finds the account, and sends warnings through the licensing bot to the admin
# chat (Nic's private test). Run it again any time to change the settings.
set -u
REPO=/opt/wolf-desk
ENV=/etc/guardian.env
DATA=/var/lib/guardian
PROV=https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai/users/current/accounts
die() { echo "ERROR: $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run with sudo"

echo "MetaApi: open app.metaapi.cloud > API access (the token page) > copy the token."
read -r -s -p "Paste the MetaApi token (it stays hidden): " TOKEN; echo
[ -n "$TOKEN" ] || die "no token"

ACCTS=$(curl -s -m 30 -H "auth-token: $TOKEN" "$PROV") || die "can't reach MetaApi"
PICK=$(printf '%s' "$ACCTS" | python3 -c '
import json, sys
try:
    a = json.load(sys.stdin)
except Exception:
    sys.exit("bad answer from MetaApi - is the token right?")
if isinstance(a, dict):
    sys.exit("MetaApi said: %s" % (a.get("message") or a))
if not a:
    sys.exit("no MT5 account on this MetaApi login yet - add it at app.metaapi.cloud first")
for i, x in enumerate(a, 1):
    print("  %d) %s  login %s  %s  [%s]" % (i, x.get("name"), x.get("login"), x.get("server"), x.get("state")), file=sys.stderr)
print(json.dumps(a))') || die "see above"
N=$(printf '%s' "$PICK" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')
CHOICE=1
if [ "$N" -gt 1 ]; then read -r -p "Which account number from the list? " CHOICE; fi
read -r ACCOUNT REGION STATE < <(printf '%s' "$PICK" | python3 -c '
import json, sys
a = json.load(sys.stdin)[int(sys.argv[1]) - 1]
print(a.get("_id") or a.get("id"), a.get("region") or "new-york", a.get("state"))' "$CHOICE") || die "bad choice"
echo "Account $ACCOUNT ($REGION, $STATE)"
if [ "$STATE" != "DEPLOYED" ]; then
    echo "Switching it on at MetaApi..."
    curl -s -m 30 -X POST -H "auth-token: $TOKEN" "$PROV/$ACCOUNT/deploy" >/dev/null
fi

# Telegram: default to the licensing bot + admin chat (grep, not source: the
# licensing env has values with spaces).
LIC=/etc/staalwag-licensing.env
BOT=$(grep '^LICENSE_BOT_TOKEN=' "$LIC" 2>/dev/null | cut -d= -f2- | tr -d '"'"'"' ')
CHAT=$(grep '^LICENSE_ADMIN_CHAT=' "$LIC" 2>/dev/null | cut -d= -f2- | tr -d '"'"'"' ')
if [ -z "$BOT" ] || [ -z "$CHAT" ]; then
    read -r -p "Telegram bot token for warnings: " BOT
    read -r -p "Your Telegram chat id: " CHAT
fi

read -r -p "Your risk per trade in % [1]: " RISK; RISK=${RISK:-1}
read -r -p "Prop challenge? Account start size in \$ (blank = not a challenge): " CSTART
DAILY=5; MAXL=10
if [ -n "$CSTART" ]; then
    read -r -p "Daily loss limit % [5]: " DAILY; DAILY=${DAILY:-5}
    read -r -p "Max loss limit % [10]: " MAXL; MAXL=${MAXL:-10}
fi

mkdir -p "$DATA" && chown wolf:wolf "$DATA"
cat > "$ENV" <<CONF
METAAPI_TOKEN=$TOKEN
METAAPI_ACCOUNT=$ACCOUNT
METAAPI_REGION=$REGION
GUARDIAN_BOT_TOKEN=$BOT
GUARDIAN_CHAT=$CHAT
RISK_PCT=$RISK
CHALLENGE_START=$CSTART
DAILY_PCT=$DAILY
MAX_PCT=$MAXL
STATE_FILE=$DATA/state.json
HOURS_FILE=$REPO/data/prime_hours.json
CALENDAR_URL=http://127.0.0.1:8777/calendar
CONF
chmod 600 "$ENV"

cp "$REPO/deploy/guardian-watch.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable guardian-watch >/dev/null 2>&1
systemctl restart guardian-watch || die "service failed to start"
curl -s -m 15 "https://api.telegram.org/bot$BOT/sendMessage" -d chat_id="$CHAT" \
    --data-urlencode text="🛡️ Guardian is now watching your MT5 account. Open a trade and it will check it within seconds." >/dev/null
sleep 20
echo -n "guardian-watch: "; systemctl is-active guardian-watch
journalctl -u guardian-watch -n 5 --no-pager -o cat
echo
echo "Done. You should have a Telegram message saying Guardian is watching."
