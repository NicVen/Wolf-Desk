#!/usr/bin/env bash
# One-time: turn on auto-ship. Run on the VPS:
#   cd /opt/wolf-desk && sudo -u wolf git pull && sudo bash deploy/autoship-setup.sh
set -e
cp /opt/wolf-desk/deploy/autoship.service /opt/wolf-desk/deploy/autoship.timer /etc/systemd/system/
systemctl daemon-reload
systemctl restart wolf-desk staalwag-licensing
systemctl enable --now autoship.timer
echo
echo "Auto-ship is ON. Anything merged into the live branch goes live within 5 minutes."
echo "You only get a Telegram message if an update fails and is rolled back."
