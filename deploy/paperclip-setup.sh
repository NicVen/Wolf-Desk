#!/usr/bin/env bash
# Put Paperclip (Nico's Trading Desk cockpit + agent orchestrator) on the VPS.
# Idempotent: safe to re-run. Run as root:  bash /opt/wolf-desk/deploy/paperclip-setup.sh
set -euo pipefail
say(){ printf "\n\033[1;36m== %s\033[0m\n" "$*"; }

REPO_URL="https://github.com/NicVen/nicos-trading-desk"
DIR=/opt/paperclip

say "1/6  Node.js (install if missing)"
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y nodejs
fi
node -v; npm -v

say "2/6  Clone / update the Paperclip repo -> $DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only || echo "  (pull skipped — local changes; that's fine)"
else
  # Private repo: this needs the box's git credentials (same as wolf-desk).
  git clone --depth 1 "$REPO_URL" "$DIR"
fi
id wolf >/dev/null 2>&1 && chown -R wolf:wolf "$DIR"

say "3/6  Warm the paperclip package (downloads @paperclipai/server once)"
sudo -u wolf bash -lc "cd '$DIR' && npx --yes paperclipai --version" || \
  echo "  (version check returned non-zero — the run service will still try)"

say "4/6  systemd service (cockpit on 127.0.0.1:3100)"
cp /opt/wolf-desk/deploy/paperclip.service /etc/systemd/system/paperclip.service
systemctl daemon-reload
systemctl enable paperclip
systemctl restart paperclip
sleep 6

say "5/6  Health"
systemctl is-active paperclip && echo "  service active" || echo "  service NOT active — see: journalctl -u paperclip -n 50 --no-pager"
curl -s -o /dev/null -w "  localhost:3100 -> HTTP %{http_code}\n" http://127.0.0.1:3100/ || true

say "6/6  Done. Caddy route (paperclip.*) is in Caddyfile.hq — reload Caddy to expose it:"
echo "  sudo cp /opt/wolf-desk/deploy/Caddyfile.hq /etc/caddy/Caddyfile && sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && sudo systemctl reload caddy"
echo
echo "  Then open:  https://paperclip.178.104.88.38.sslip.io  (same password as the cloud desktop)"
echo "  To run agents you'll also need an AI CLI (claude / gemini) installed + logged in on the box."
