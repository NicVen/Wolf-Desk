#!/usr/bin/env bash
# Run the Gold (Staalwag Signals) and VELDRIN (Veldrin Forex Signals) desks on
# this server. Railway is gone; this replaces it. Safe to run again: it updates
# the code, keeps settings that already work, and only asks for what's missing.
#   cd /opt/wolf-desk && sudo -u wolf git pull && sudo bash deploy/desks-setup.sh
#
# Per desk it asks for the bot token (BotFather -> the bot -> API Token) and
# checks the bot is an admin of its channel. Prices come from Yahoo (free, no key).
set -u
WOLF=/opt/wolf-desk
die() { echo "ERROR: $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run with sudo"
command -v python3 >/dev/null || die "python3 missing"
apt-get install -y python3-venv git >/dev/null 2>&1

tg() { curl -s -m 15 "https://api.telegram.org/bot$1/$2"; }
jget() { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1]))" "$1" 2>/dev/null; }
setkey() {  # setkey FILE KEY VALUE -- replace or append
    if grep -q "^$2=" "$1"; then sed -i "s|^$2=.*|$2=$3|" "$1"; else echo "$2=$3" >> "$1"; fi
}

echo -n "Yahoo prices from this server: "
code=$(curl -s -m 15 -o /dev/null -w "%{http_code}" -A "Mozilla/5.0" \
  "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?range=1d&interval=15m")
[ "$code" = 200 ] && echo OK || echo "FAILED ($code) - desks will run but stay quiet"

# desk  repo  port  label  channel  cycle-seconds
setup_desk() {
    local NAME=$1 REPO=$2 PORT=$3 LABEL=$4 CHANNEL=$5 CYCLE=$6
    local DIR=/opt/$NAME ENV=/etc/$NAME.env DATA=/var/lib/$NAME
    echo; echo "=== $NAME -> $CHANNEL"

    # 1. Code
    if [ -d "$DIR/.git" ]; then
        git config --global --add safe.directory "$DIR" 2>/dev/null
        git -C "$DIR" pull -q || echo "  (pull failed, using the copy already here)"
    else
        git clone -q "https://github.com/NicVen/$REPO" "$DIR" || die "can't download $REPO (private repo?)"
    fi
    python3 -m venv "$DIR/.venv" >/dev/null || die "venv failed"
    "$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt" || die "pip install failed"
    mkdir -p "$DATA"; chown -R wolf:wolf "$DIR" "$DATA"

    # 2. Settings
    [ -f "$ENV" ] || touch "$ENV"
    chmod 600 "$ENV"
    local TOKEN; TOKEN=$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' "$ENV" | tail -1)
    local BOT=""
    [ -n "$TOKEN" ] && BOT=$(tg "$TOKEN" getMe | jget 'd["result"]["username"]')
    while [ -z "$BOT" ]; do
        read -r -p "  Paste the bot token for $CHANNEL: " TOKEN
        [ -n "$TOKEN" ] || die "no token"
        BOT=$(tg "$TOKEN" getMe | jget 'd["result"]["username"]')
        [ -n "$BOT" ] || echo "  Telegram doesn't accept that token, try again."
    done
    echo "  bot: @$BOT"

    local CHAT; CHAT=$(tg "$TOKEN" "getChat?chat_id=$CHANNEL" | jget 'd["result"]["id"]')
    local ROLE=""
    [ -n "$CHAT" ] && ROLE=$(tg "$TOKEN" "getChatMember?chat_id=$CHAT&user_id=$(echo "$TOKEN" | cut -d: -f1)" \
        | jget 'd["result"]["status"]')
    if [ "$ROLE" = administrator ] || [ "$ROLE" = creator ]; then
        echo "  channel: OK (@$BOT is admin, id $CHAT)"
    else
        echo "  channel: NOT READY - add @$BOT as an admin of $CHANNEL (allow 'Post messages'), then run this again."
        CHAT=${CHAT:-$CHANNEL}
    fi

    setkey "$ENV" TELEGRAM_BOT_TOKEN "$TOKEN"
    setkey "$ENV" TELEGRAM_CHAT_ID "$CHAT"
    setkey "$ENV" FEED web
    setkey "$ENV" DESK_LABEL "$LABEL"
    setkey "$ENV" PORT "$PORT"
    # Ledger = the track record. Keep it on disk, never in /tmp (wiped on restart).
    local LEDGER; LEDGER=$(sed -n 's/^LEDGER_PATH=//p' "$ENV" | tail -1)
    case "$LEDGER" in ""|/tmp/*|/data/*) setkey "$ENV" LEDGER_PATH "$DATA/${NAME%-desk}.db" ;; esac
    grep -q "^CYCLE_SECONDS=" "$ENV" || echo "CYCLE_SECONDS=$CYCLE" >> "$ENV"

    # 3. Service
    cp "$WOLF/deploy/$NAME.service" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable "$NAME" >/dev/null 2>&1
    systemctl restart "$NAME" || die "$NAME failed to start"
    sleep 5
    echo -n "  service: "; systemctl is-active "$NAME"
    echo -n "  record:  "; curl -s -m 5 "http://127.0.0.1:$PORT/track_record.json" | head -c 120; echo
}

setup_desk staalwag-desk Staalwag-desk 8781 GOLD    @staalwagsignals 120
setup_desk veldrin-desk  Veldrin-Desk  8782 VELDRIN @veldrinforex   300

systemctl try-restart wolf-desk
echo
echo "Done. HQ reads the results at:"
echo "  https://staalwag.com/desks/gold/track_record.json"
echo "  https://staalwag.com/desks/fx/track_record.json"
echo "Logs: journalctl -u staalwag-desk -n 30   (or veldrin-desk)"
