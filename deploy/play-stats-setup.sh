#!/usr/bin/env bash
# One-time: connect staalwag.com/stats to Google Play's own install reports.
#   sudo bash /opt/wolf-desk/deploy/play-stats-setup.sh
# It asks for (1) the robot account's key file text and (2) the Cloud Storage
# URI from Play Console > Download reports > Statistics > "Copy Cloud Storage URI".
set -euo pipefail
KEY=/etc/staalwag-play.json
REPO=/opt/wolf-desk
TMP=$(mktemp); chmod 600 "$TMP"; trap 'rm -f "$TMP"' EXIT

echo "1) Paste the WHOLE key file text (starts with { and ends with }),"
echo "   then press Enter, then Ctrl+D:"
cat > "$TMP"
echo
read -r -p "2) Paste the Cloud Storage URI (gs://pubsite_prod_...): " URI

python3 - "$TMP" "$URI" "$KEY" <<'PY'
import json, sys
src, uri, dst = sys.argv[1:4]
k = json.load(open(src))
for f in ("client_email", "private_key"):
    if not k.get(f):
        sys.exit("That doesn't look like a service account key (missing %s)." % f)
b = uri.strip()
b = b[5:] if b.startswith("gs://") else b
k["bucket"] = b.split("/")[0]
if not k["bucket"]:
    sys.exit("The Cloud Storage URI is empty.")
json.dump(k, open(dst, "w"))
print("Saved for", k["client_email"], "-> bucket", k["bucket"])
PY
chown wolf:wolf "$KEY"; chmod 600 "$KEY"

echo "Testing a sync..."
if sudo -u wolf python3 "$REPO/play_sync.py" | head -20; then
  systemctl restart wolf-desk
  echo "DONE. Open https://staalwag.com/stats"
else
  echo "Test failed. If it says 403/permission: Google can take up to 24 hours to switch"
  echo "the robot account on. It retries every 6 hours by itself; nothing else to do."
  systemctl restart wolf-desk
fi
