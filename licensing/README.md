# STAALWAG Licensing

Replaces the MQL5 marketplace for renting EAs and indicators. Clients pay with
crypto (NOWPayments); a **rolling activation code** unlocks the product and
**renews automatically on payment**; a missed renewal triggers a reminder and
**access is removed 4 hours later**.

## How it works

```
client → /buy?product=GOLD → NOWPayments hosted checkout → pays in crypto
                                        │
                          NOWPayments → /ipn (HMAC-verified)
                                        │
                          license set ACTIVE, paid_until += period,
                          client messaged their activation key
                                        │
EA/indicator (with the key) → /verify?key=&account=&machine=&product=
                                        │
                          server checks paid_until (+ binds to first account),
                          returns {valid:true, expires_at, rolling token}
```

- **Rolling code:** every `/verify` returns a fresh signed token; it changes on
  each check-in and each renewal, so a shared/stale code stops working.
- **Anti-sharing:** a license binds to the first MT5 account (+ broker) that uses
  it; other accounts are refused.
- **Grace/revoke:** at expiry the client is warned; `GRACE_HOURS` (default 4)
  later, if still unpaid, the license is revoked and the EA blocks.

## Endpoints
| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/verify` | EA/indicator | check-in; returns valid + rolling token |
| POST | `/ipn` | NOWPayments | payment webhook (HMAC-verified) |
| POST | `/checkout` | buy page | create a payment, returns `invoice_url` |
| GET | `/buy?product=CODE` | client | minimal hosted buy page |
| POST | `/admin/issue` | you (`X-Admin-Token`) | comp / manually extend a license |
| GET | `/` | — | health + product list |

## Products
Defined in `config.py` (`PRODUCTS`) — code, name, price (USD), period (days).
Edit and `systemctl restart staalwag-licensing`.

## Deploy (on the VPS)
```bash
cd /opt/wolf-desk && sudo -u wolf git pull
cp deploy/licensing.env.example /etc/staalwag-licensing.env
python3 -c "import secrets;print('SIGNING',secrets.token_urlsafe(32));print('ADMIN',secrets.token_urlsafe(32))"
nano /etc/staalwag-licensing.env      # paste NOWPayments keys + the two secrets
chmod 600 /etc/staalwag-licensing.env
cp deploy/staalwag-licensing.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now staalwag-licensing
cp deploy/Caddyfile.hq /etc/caddy/Caddyfile.new \
  && caddy validate --config /etc/caddy/Caddyfile.new --adapter caddyfile \
  && mv /etc/caddy/Caddyfile.new /etc/caddy/Caddyfile && systemctl reload caddy
```
Then in NOWPayments → Instant payment notifications, set the **Webhook URL** to:
`https://pay.178.104.88.38.sslip.io/ipn`

Test: `curl https://pay.178.104.88.38.sslip.io/` → product list.

## MQL5 side
`experts/LicenseCheck.mqh` — add the `pay.*` URL to the terminal's allowed
WebRequest URLs, then gate the EA with `LicenseOK(LicenseKey, "GOLD")`.

Stdlib only — runs in the existing `wolf-desk` venv. No secrets in git.
