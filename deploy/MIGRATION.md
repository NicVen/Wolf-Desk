# STAALWAG HQ — migrate everything to one VPS

Stands up the whole estate on your Hetzner box (`178.104.88.38`) behind one Caddy
with automatic HTTPS, reachable from **one desktop link**:

> ## 🔗 https://178.104.88.38.sslip.io
> The **STAALWAG HQ** hub — links to every desk. Bookmark it / pin it to your
> desktop. (Live once the steps below are done. Swap in a real domain later and
> the hub's links follow automatically.)

## The estate

| Service | Repo | On the VPS | Reached at |
|---|---|---|---|
| **STAALWAG HQ** hub | Wolf-Desk `deploy/hub` | static | `178.104.88.38.sslip.io` |
| **WOLF Intraday Desk** (PWA + STAALCALIBUR engine) | `Wolf-Desk` | Python, port 8777 | `wolf.…sslip.io/app` |
| **EA Forge** (builder) | `ea-forge` | static | `forge.…sslip.io` |
| **STAALWAG Desk** (Gold/indices signals + track) | `Staalwag-desk` | Python worker, port 8781 | `staalwag.…sslip.io` |
| **VELDRIN Desk** (FX signals + track) | `Veldrin-Desk` | Python worker, port 8782 | `veldrin.…sslip.io` |

> **The MT5 EAs stay on your PC.** The `.mq5` experts in `Staalwag-desk/experts`
> run inside MetaTrader on your machine, not the VPS. They keep gating on the
> desk's regime via the PC bridge (`deploy/START_PC_BRIDGE.bat`, pointed at
> `https://wolf.178.104.88.38.sslip.io`).

Run everything below over SSH as `root` (`ssh root@178.104.88.38`).

---

## 1. Base + user + firewall

```bash
apt update && apt -y upgrade
apt -y install python3 python3-venv git ufw curl
adduser --disabled-password --gecos "" wolf
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable
```

Only 80/443 are open. Every app port (8777/8781/8782) is reachable **only through
Caddy**, even though some bind 0.0.0.0 — ufw closes them to the internet.

## 2. Clone all four repos into /opt

```bash
cd /opt
git clone https://github.com/NicVen/Wolf-Desk      wolf-desk
git -C wolf-desk checkout claude/excalibur-v13-markov-omnibus-mm85xk
git clone https://github.com/NicVen/ea-forge       ea-forge
git clone https://github.com/NicVen/Staalwag-desk  staalwag-desk
git clone https://github.com/NicVen/Veldrin-Desk   veldrin-desk
```

## 3. Python envs (the three Python services; ea-forge is static)

```bash
for d in wolf-desk staalwag-desk veldrin-desk; do
  python3 -m venv /opt/$d/.venv
  /opt/$d/.venv/bin/pip install -r /opt/$d/requirements.txt
done
mkdir -p /opt/wolf-desk/markov_out
chown -R wolf:wolf /opt/wolf-desk /opt/ea-forge /opt/staalwag-desk /opt/veldrin-desk
```

## 4. Environment files (secrets — never committed)

**WOLF Intraday Desk:**
```bash
cp /opt/wolf-desk/deploy/wolf-desk.env.example /etc/wolf-desk.env
python3 -c "import secrets; print('WOLF_PASS =', secrets.token_urlsafe(24))"
nano /etc/wolf-desk.env      # paste WOLF_PASS; keep BIND_ADDR=127.0.0.1, PORT=8777
chmod 600 /etc/wolf-desk.env
```

**STAALWAG Desk** (Telegram + data key; note the port):
```bash
cp /opt/staalwag-desk/.env.example /etc/staalwag-desk.env
echo "PORT=8781" >> /etc/staalwag-desk.env
nano /etc/staalwag-desk.env  # TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TWELVEDATA_API_KEY, FEED=web
chmod 600 /etc/staalwag-desk.env
```

**VELDRIN Desk:**
```bash
cp /opt/veldrin-desk/.env.example /etc/veldrin-desk.env
echo "PORT=8782" >> /etc/veldrin-desk.env
nano /etc/veldrin-desk.env   # TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TWELVEDATA_API_KEY
chmod 600 /etc/veldrin-desk.env
```

> These two desks are your existing Telegram signal bots — they need the same
> tokens/keys you already use. Without them the workers run but stay quiet.

## 5. Services (auto-start, auto-restart)

```bash
cp /opt/wolf-desk/deploy/wolf-desk.service      /etc/systemd/system/
cp /opt/wolf-desk/deploy/staalwag-desk.service  /etc/systemd/system/
cp /opt/wolf-desk/deploy/veldrin-desk.service   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now wolf-desk staalwag-desk veldrin-desk
systemctl status wolf-desk staalwag-desk veldrin-desk --no-pager
```

## 6. Caddy — automatic HTTPS for the hub + every subdomain

```bash
apt -y install debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt update && apt -y install caddy

cp /opt/wolf-desk/deploy/Caddyfile.hq /etc/caddy/Caddyfile
systemctl reload caddy
journalctl -u caddy --no-pager | tail -30    # watch it obtain 5 certificates
```

Give it ~1 minute (it fetches a cert per hostname).

## 7. Open it

**Desktop:** open **https://178.104.88.38.sslip.io** → the STAALWAG HQ hub. Pin it.
**Phone:** from the hub tap **WOLF Intraday Desk** → enter WOLF_PASS → Chrome ⋮ → Install app.

## 8. Keep the MT5 bridge alive on your PC

The engine writes gate files on the VPS; your EAs read them on the PC. On the PC:
```
setx WOLF_HOST "https://wolf.178.104.88.38.sslip.io"
setx WOLF_PASS "your-wolf-key"
```
then run `deploy\START_PC_BRIDGE.bat` (from your Wolf-Desk checkout). It pulls
`/markov.json` every 5 min and writes `markov_<SYMBOL>.txt` into MT5 `Common\Files`.

---

## Maintenance

**Update a service:**
```bash
cd /opt/wolf-desk && sudo -u wolf git pull && systemctl restart wolf-desk
# ea-forge / staalwag-desk / veldrin-desk: git pull in /opt/<repo>, then restart if Python
```

**Backups:** enable Hetzner automated backups in the console, or:
```bash
tar czf /root/hq-backup-$(date +%F).tgz \
  -C /opt wolf-desk/data wolf-desk/growth.db staalwag-desk veldrin-desk 2>/dev/null
```

**Real domain later:** point DNS A-records (`@`, `wolf`, `forge`, `staalwag`,
`veldrin`) at `178.104.88.38`, replace the site addresses in `/etc/caddy/Caddyfile`,
`systemctl reload caddy`. The hub relinks itself; reinstall the PWA from the new URL.

**Security:** `WOLF_PASS` guards the WOLF desk; rotate via `/etc/wolf-desk.env` +
`systemctl restart wolf-desk`. `ufw status` should show only OpenSSH, 80, 443.
Keep the box patched (`apt update && apt upgrade`).
