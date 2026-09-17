# WOLF Desk — VPS deployment runbook

Puts the Excalibur engine on your Hetzner VPS behind Caddy (automatic HTTPS),
so the phone PWA works anywhere. No domain required — we use a free `sslip.io`
name that maps to your IP; swap in a real domain later by editing one line.

- **Server:** `178.104.88.38` (Ubuntu, Hetzner)
- **Public URL when done:** `https://178.104.88.38.sslip.io/app`
- **App port:** `8777`, bound to `127.0.0.1` (only Caddy faces the internet)

Run the commands below over SSH as `root` (Hetzner console → or `ssh root@178.104.88.38`).

---

## 1. Base packages + a non-root user

```bash
apt update && apt -y upgrade
apt -y install python3 python3-venv git ufw
adduser --disabled-password --gecos "" wolf
```

## 2. Firewall (this is the "open the exact port" step)

Caddy serves 80/443; the app port 8777 stays private, so we do NOT open it.

```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status
```

## 3. Get the code

```bash
git clone https://github.com/NicVen/Wolf-Desk /opt/wolf-desk
cd /opt/wolf-desk
git checkout claude/excalibur-v13-markov-omnibus-mm85xk
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
mkdir -p markov_out
chown -R wolf:wolf /opt/wolf-desk
```

## 4. Environment file (holds your secret key — never committed)

```bash
cp /opt/wolf-desk/deploy/wolf-desk.env.example /etc/wolf-desk.env
# generate a strong key and paste it into WOLF_PASS:
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
nano /etc/wolf-desk.env      # set WOLF_PASS=<that key>; leave BIND_ADDR=127.0.0.1
chmod 600 /etc/wolf-desk.env
```

## 5. Run the app as a service (auto-starts, auto-restarts)

```bash
cp /opt/wolf-desk/deploy/wolf-desk.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now wolf-desk
systemctl status wolf-desk --no-pager      # should say active (running)
# quick local check (should return JSON, using your key):
curl "http://127.0.0.1:8777/data?class=fx&key=YOUR_KEY" | head -c 200
```

## 6. Caddy — automatic HTTPS

```bash
apt -y install debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt update && apt -y install caddy

cp /opt/wolf-desk/deploy/Caddyfile /etc/caddy/Caddyfile
systemctl reload caddy
journalctl -u caddy --no-pager | tail -20    # watch it obtain the certificate
```

Give it ~30 seconds to fetch the cert. Then from any browser:

```
https://178.104.88.38.sslip.io/app
```

## 7. Install the app on your phone

1. Open **Chrome** → `https://178.104.88.38.sslip.io/app`
2. Enter your **WOLF_PASS** → **Connect**
3. Chrome menu (⋮) → **Install app** → standalone icon, works anywhere on any network.

---

## Backups (Hetzner) + data

Turn on Hetzner's automated backups in the console (small monthly add-on), or
snapshot before changes. The only state to protect is on disk:

```bash
# ad-hoc backup of the data + marketing db
tar czf /root/wolf-backup-$(date +%F).tgz -C /opt/wolf-desk data growth.db 2>/dev/null
```

## Keeping the MT5 bridge alive (engine on VPS, EAs on your PC)

The VPS writes gate files on the VPS. To feed the EAs on your **PC**, run the
puller there — it pulls `GET /markov.json` and writes the gate files into MT5's
`Common\Files`:

1. On the PC, in the repo: `deploy\START_PC_BRIDGE.bat`
2. Set once (so it's remembered): `setx WOLF_HOST "https://178.104.88.38.sslip.io"` and `setx WOLF_PASS "your-key"`
3. In each EA, keep the Markov gate ON; Gold uses `markov_regime.txt`, others use `markov_<SYMBOL>.txt`.

## Updating the server later

```bash
cd /opt/wolf-desk && sudo -u wolf git pull
systemctl restart wolf-desk
```

## Swapping in a real domain later

Point the domain's DNS **A record** at `178.104.88.38`, then edit the first line
of `/etc/caddy/Caddyfile` to your domain and `systemctl reload caddy`. Update the
PWA URL you use on the phone; reinstall it once from the new address.

## Security notes

- `WOLF_PASS` is the only lock on the public URL — keep it long/random; to
  rotate, edit `/etc/wolf-desk.env` and `systemctl restart wolf-desk`.
- The app port (8777) is never exposed; only Caddy (80/443) is. `ufw status`
  should show only OpenSSH, 80, 443.
- Keep the box patched: `apt update && apt upgrade` periodically.
