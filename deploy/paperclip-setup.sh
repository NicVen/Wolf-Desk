#!/usr/bin/env bash
# Put Paperclip (Nico's Trading Desk cockpit + agent orchestrator) on the VPS.
# Idempotent: safe to re-run. Run as root:  bash /opt/wolf-desk/deploy/paperclip-setup.sh
set -uo pipefail
say(){ printf "\n\033[1;36m== %s\033[0m\n" "$*"; }

REPO_URL="https://github.com/NicVen/nicos-trading-desk"
DIR=/opt/paperclip

say "1/6  Locate Node / npm / npx (install only if truly missing)"
NODE_BIN="$(command -v node || true)"
NODE_DIR="$( [ -n "$NODE_BIN" ] && dirname "$NODE_BIN" || echo "" )"
NPX_BIN="$(command -v npx || true)"; [ -z "$NPX_BIN" ] && [ -n "$NODE_DIR" ] && [ -x "$NODE_DIR/npx" ] && NPX_BIN="$NODE_DIR/npx"
NPM_BIN="$(command -v npm || true)"; [ -z "$NPM_BIN" ] && [ -n "$NODE_DIR" ] && [ -x "$NODE_DIR/npm" ] && NPM_BIN="$NODE_DIR/npm"
# common fallback locations
for c in /usr/bin/npx /usr/local/bin/npx /opt/node/bin/npx /root/.nvm/versions/node/*/bin/npx; do
  [ -z "$NPX_BIN" ] && [ -x "$c" ] && NPX_BIN="$c"
done
if [ -z "$NPX_BIN" ]; then
  echo "  npx not found — installing Node LTS via NodeSource"
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y nodejs
  NODE_BIN="$(command -v node)"; NODE_DIR="$(dirname "$NODE_BIN")"
  NPX_BIN="$(command -v npx)"; NPM_BIN="$(command -v npm)"
fi
NODE_DIR="$(dirname "$NPX_BIN")"
echo "  node: ${NODE_BIN:-?}   npx: $NPX_BIN   (bin dir: $NODE_DIR)"
[ -x "$NPX_BIN" ] || { echo "  FATAL: still no npx. Install Node manually."; exit 1; }

say "2/6  Clone / update the Paperclip repo -> $DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only || echo "  (pull skipped — local changes; that's fine)"
else
  git clone --depth 1 "$REPO_URL" "$DIR" || {
    echo "  Clone failed — the private repo needs git access on this box."
    echo "  Fix: give the box a token, e.g.:"
    echo "     git clone https://<GITHUB_TOKEN>@github.com/NicVen/nicos-trading-desk $DIR"
    exit 1; }
fi
id wolf >/dev/null 2>&1 && chown -R wolf:wolf "$DIR"

say "3/6  Warm the paperclip package (first run downloads @paperclipai/server)"
sudo -u wolf env "PATH=$NODE_DIR:$PATH" bash -lc "cd '$DIR' && '$NPX_BIN' --yes paperclipai --version" \
  || echo "  (version probe non-zero — the service will still try to run it)"

say "4/6  Write + start the systemd service (cockpit on 127.0.0.1:3100)"
cat > /etc/systemd/system/paperclip.service <<UNIT
[Unit]
Description=Paperclip — Nico's Trading Desk (cockpit + agent orchestrator)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=wolf
WorkingDirectory=$DIR
Environment=HOST=127.0.0.1
Environment=PORT=3100
Environment=PATH=$NODE_DIR:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=$NPX_BIN --yes paperclipai run
Restart=always
RestartSec=8
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable paperclip
systemctl restart paperclip
sleep 8

say "5/6  Health"
systemctl is-active paperclip && echo "  service active" || echo "  NOT active -> journalctl -u paperclip -n 60 --no-pager"
curl -s -o /dev/null -w "  localhost:3100 -> HTTP %{http_code}\n" http://127.0.0.1:3100/ || true

say "6/6  Expose via Caddy (run this next):"
echo "  sudo cp /opt/wolf-desk/deploy/Caddyfile.hq /etc/caddy/Caddyfile && sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && sudo systemctl reload caddy"
echo "  then open  https://paperclip.178.104.88.38.sslip.io  (cloud-desktop password)"
