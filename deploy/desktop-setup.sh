#!/usr/bin/env bash
# =============================================================================
# STAALWAG cloud desktop — Milestone 1
# Turns the VPS into a remote workstation you reach from ANY computer's browser:
#     https://desk.178.104.88.38.sslip.io   (login: nico / <DESK_PASS>)
#
# Stack: XFCE (lightweight desktop) + TigerVNC (localhost only) + noVNC
#        (browser client) behind the Caddy you already run (HTTPS + password).
# Nothing new is exposed to the internet: VNC binds to localhost, Caddy is the
# only door, and a wrong Caddyfile can never take your desks down — the script
# validates the config and refuses to reload if it is bad.
#
# Run as root on the VPS:
#     cd /opt/wolf-desk && sudo -u wolf git pull
#     sudo DESK_PASS='choose-a-strong-pass' bash deploy/desktop-setup.sh
# (Omit DESK_PASS and one is generated and printed at the end.)
# Re-runnable: safe to run again to repair/update.
# =============================================================================
set -uo pipefail

DESK_USER="root"
DESK_HOME="/root"
VNC_DISPLAY="1"
VNC_PORT="5901"      # 5900 + display
NOVNC_PORT="6080"
GEOMETRY="${GEOMETRY:-1600x900}"
DESK_USERNAME="nico"

say(){ printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
warn(){ printf '\033[1;33m[!] %s\033[0m\n' "$*"; }
die(){ printf '\033[1;31m[FATAL] %s\033[0m\n' "$*"; exit 1; }

[ "$(id -u)" = "0" ] || die "Run as root (use sudo)."

# ---------------------------------------------------------------------------
say "1/8  Installing XFCE, TigerVNC, noVNC"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y || die "apt update failed"
apt-get install -y --no-install-recommends \
  xfce4 xfce4-terminal xfce4-goodies dbus-x11 \
  tigervnc-standalone-server tigervnc-common \
  novnc websockify \
  x11-xserver-utils xterm openssl wget ca-certificates \
  || die "package install failed"

# ---------------------------------------------------------------------------
say "2/8  Installing Firefox (real .deb, not snap — snap breaks under VNC)"
install -d -m 0755 /etc/apt/keyrings
if wget -qO /etc/apt/keyrings/packages.mozilla.org.asc https://packages.mozilla.org/apt/repo-signing-key.gpg; then
  echo "deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.asc] https://packages.mozilla.org/apt mozilla main" \
    > /etc/apt/sources.list.d/mozilla.list
  printf 'Package: *\nPin: origin packages.mozilla.org\nPin-Priority: 1000\n' \
    > /etc/apt/preferences.d/mozilla
  apt-get update -y && apt-get install -y firefox || warn "Firefox install failed — desktop still works, install a browser later."
else
  warn "Could not fetch Mozilla key — skipping Firefox; you can install one from the desktop later."
fi

# ---------------------------------------------------------------------------
say "3/8  Password for the desktop (Caddy gate)"
if [ -z "${DESK_PASS:-}" ]; then
  DESK_PASS="$(openssl rand -base64 12 | tr -dc 'A-Za-z0-9' | cut -c1-14)"
  GENERATED=1
fi
command -v caddy >/dev/null 2>&1 || die "caddy not found — run the migration Caddy step first."
HASH="$(caddy hash-password --plaintext "$DESK_PASS" 2>/dev/null)" || die "caddy hash-password failed"
cat > /etc/caddy/desk-auth.conf <<EOF
basic_auth {
	${DESK_USERNAME} ${HASH}
}
EOF
# 0644 so the `caddy` user can read it at reload (it holds a bcrypt hash, not
# the plaintext password). 0600/root-owned makes `caddy reload` fail to import.
chmod 644 /etc/caddy/desk-auth.conf

# ---------------------------------------------------------------------------
say "4/8  Desktop launcher (Xtigervnc directly — skips the buggy migration)"
# Clean any half-migrated TigerVNC state from a previous attempt.
rm -rf "$DESK_HOME/.vnc" "$DESK_HOME/.config/tigervnc" 2>/dev/null || true
# Launch the VNC X server directly + XFCE on it. Bypasses the tigervncserver
# wrapper (whose ~/.vnc -> ~/.config/tigervnc migration fails on Ubuntu 26.04).
cat > /usr/local/bin/staalwag-vnc.sh <<EOF
#!/bin/sh
export HOME=${DESK_HOME}
export USER=${DESK_USER}
export DISPLAY=:${VNC_DISPLAY}
export XDG_CURRENT_DESKTOP=XFCE
export XDG_SESSION_TYPE=x11
# -localhost keeps the RFB port on loopback; Caddy is the only way in.
/usr/bin/Xtigervnc :${VNC_DISPLAY} -rfbport ${VNC_PORT} -SecurityTypes None \\
  -localhost -geometry ${GEOMETRY} -depth 24 -desktop STAALWAG >/var/log/staalwag-vnc.log 2>&1 &
XPID=\$!
sleep 3
dbus-launch --exit-with-session startxfce4
kill \$XPID 2>/dev/null
EOF
chmod +x /usr/local/bin/staalwag-vnc.sh

# ---------------------------------------------------------------------------
say "5/8  systemd services (desktop + web bridge)"
cat > /etc/systemd/system/staalwag-desktop.service <<EOF
[Unit]
Description=STAALWAG cloud desktop (Xtigervnc + XFCE)
After=network.target

[Service]
Type=simple
User=${DESK_USER}
Environment=HOME=${DESK_HOME}
WorkingDirectory=${DESK_HOME}
ExecStart=/usr/local/bin/staalwag-vnc.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/staalwag-novnc.service <<EOF
[Unit]
Description=STAALWAG desktop web bridge (noVNC / websockify)
After=staalwag-desktop.service
Wants=staalwag-desktop.service

[Service]
ExecStart=/usr/bin/websockify --web=/usr/share/novnc 127.0.0.1:${NOVNC_PORT} localhost:${VNC_PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now staalwag-desktop.service || die "desktop service failed to start"
sleep 2
systemctl enable --now staalwag-novnc.service   || die "novnc service failed to start"

# ---------------------------------------------------------------------------
say "6/8  Desktop icons (links to every desk)"
DESKTOP_DIR="$DESK_HOME/Desktop"
mkdir -p "$DESKTOP_DIR"
make_link(){ # name  url  icon
  local f="$DESKTOP_DIR/$1.desktop"
  cat > "$f" <<EOF
[Desktop Entry]
Version=1.0
Type=Link
Name=$1
URL=$2
Icon=$3
EOF
  chmod +x "$f"
}
make_link "STAALWAG HQ"        "https://hq.178.104.88.38.sslip.io"       "utilities-system-monitor"
make_link "Paperclip"          "https://paperclip.178.104.88.38.sslip.io" "accessories-text-editor"
make_link "HQ Hub"             "https://178.104.88.38.sslip.io"          "user-home"
make_link "WOLF Intraday Desk" "https://wolf.178.104.88.38.sslip.io"     "applications-office"
make_link "STAALCALIBUR App"   "https://app.178.104.88.38.sslip.io"      "phone"
make_link "EA Forge"           "https://forge.178.104.88.38.sslip.io"    "applications-engineering"
make_link "STAALWAG Desk"      "https://staalwag.178.104.88.38.sslip.io" "emblem-favorite"
make_link "VELDRIN Desk"       "https://veldrin.178.104.88.38.sslip.io"  "emblem-favorite"
# a folder for the project code (HQ engine lands here in Milestone 2)
mkdir -p "$DESK_HOME/STAALWAG-Projects"
ln -sfn "$DESK_HOME/STAALWAG-Projects" "$DESKTOP_DIR/STAALWAG-Projects" 2>/dev/null || true
chown -R "$DESK_USER":"$DESK_USER" "$DESK_HOME/.vnc" "$DESKTOP_DIR" "$DESK_HOME/STAALWAG-Projects" 2>/dev/null || true

# ---------------------------------------------------------------------------
say "7/8  Wiring the desktop into Caddy (validated — safe for your live desks)"
cp /opt/wolf-desk/deploy/Caddyfile.hq /etc/caddy/Caddyfile.new
if caddy validate --config /etc/caddy/Caddyfile.new --adapter caddyfile >/dev/null 2>&1; then
  mv /etc/caddy/Caddyfile.new /etc/caddy/Caddyfile
  systemctl reload caddy && say "Caddy reloaded OK"
else
  rm -f /etc/caddy/Caddyfile.new
  warn "New Caddyfile did NOT validate — your existing desks are untouched."
  warn "Run: caddy validate --config /opt/wolf-desk/deploy/Caddyfile.hq --adapter caddyfile"
  warn "and send me the error. (Most likely the basic_auth directive name.)"
fi

# ---------------------------------------------------------------------------
say "8/8  Done"
echo    "-------------------------------------------------------------"
echo    "  Cloud desktop:  https://desk.178.104.88.38.sslip.io"
echo    "  Login user:     ${DESK_USERNAME}"
if [ "${GENERATED:-0}" = "1" ]; then
  echo  "  Password:       ${DESK_PASS}    <-- SAVE THIS NOW"
else
  echo  "  Password:       (the DESK_PASS you set)"
fi
echo    "-------------------------------------------------------------"
echo    "  Services:  systemctl status staalwag-desktop staalwag-novnc"
echo    "  Open the URL in any browser -> click 'Connect' -> your desktop."
echo    "-------------------------------------------------------------"
