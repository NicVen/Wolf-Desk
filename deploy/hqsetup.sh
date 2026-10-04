#!/usr/bin/env bash
# STAALWAG HQ — interactive setup for the two Telegram signal desks on the VPS.
# Avoids fragile multi-line pasting: run it once and it PROMPTS for each secret
# (paste one value per prompt). Run as root:
#   bash /opt/wolf-desk/deploy/hq_setup.sh
DEPLOY=/opt/wolf-desk/deploy

clone_and_venv() {
  local repo="$1" dir="$2"
  cd /opt || return 1
  if [ ! -d "$dir" ]; then
    echo "  cloning $repo ..."
    git clone "https://github.com/NicVen/$repo" "$dir" || { echo "  clone failed"; return 1; }
  fi
  python3 -m venv "/opt/$dir/.venv"
  "/opt/$dir/.venv/bin/pip" install -q -r "/opt/$dir/requirements.txt"
  chown -R wolf:wolf "/opt/$dir"
}

setup_desk() {
  local name="$1" port="$2" envfile="$3" extra="$4"
  echo
  echo "=================================================="
  echo "  $name desk — paste each value, then press Enter"
  echo "=================================================="
  read -rp "  Telegram BOT TOKEN : " TOK
  read -rp "  Telegram CHAT ID   : " CHAT
  read -rp "  TWELVEDATA API KEY : " TD
  umask 077
  {
    echo "TELEGRAM_BOT_TOKEN=$TOK"
    echo "TELEGRAM_CHAT_ID=$CHAT"
    echo "TWELVEDATA_API_KEY=$TD"
    echo "PAPER_MODE=true"
    echo "FEED=web"
    echo "PORT=$port"
    printf '%s\n' "$extra"
  } > "$envfile"
  chmod 600 "$envfile"
}

echo "Installing the two signal desks (clone + Python packages)..."
clone_and_venv Staalwag-desk staalwag-desk || exit 1
clone_and_venv Veldrin-Desk  veldrin-desk  || exit 1

setup_desk "STAALWAG" 8781 /etc/staalwag-desk.env \
"DESK_LABEL=STAALWAG
CYCLE_SECONDS=60
LEDGER_PATH=/opt/staalwag-desk/staalwag.db"

setup_desk "VELDRIN" 8782 /etc/veldrin-desk.env \
"DESK_LABEL=VELDRIN
CYCLE_SECONDS=300
LEDGER_PATH=/opt/veldrin-desk/veldrin.db"

cp "$DEPLOY/staalwag-desk.service" /etc/systemd/system/
cp "$DEPLOY/veldrin-desk.service"  /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now staalwag-desk veldrin-desk
sleep 4

echo
echo "----- RESULT -----"
echo -n "staalwag-desk: "; systemctl is-active staalwag-desk
echo -n "veldrin-desk : "; systemctl is-active veldrin-desk
echo "--- staalwag log (last 8) ---"; journalctl -u staalwag-desk --no-pager | tail -8
echo "--- veldrin log (last 8) ---";  journalctl -u veldrin-desk  --no-pager | tail -8
echo "----- END -----"
