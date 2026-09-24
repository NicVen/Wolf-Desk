# STAALCALIBUR storefront (isolated sales funnel)

A standalone, advertisable sales page for the STAALCALIBUR mobile app, with a
**paywalled / trial-gated** download. Fully isolated — it does **not** change the
existing app, site, WOLF desk, or download routes. You can link it anywhere:

    https://staalwag.com/store          (also /get-app)

## The funnel

    sales page  ──►  Start free trial ─┐
                                       ├─►  activation key  ──►  /app/get?key=…  ──►  APK
                     Buy (crypto/card)─┘        (issued by the licensing service)

The **key is the paywall**, not the APK file: the app is inert until you unlock it
with a valid key. The download route `/app/get` refuses to serve the APK without a
live licence (trial **or** paid), so the advertised funnel only hands over the app
to someone who has claimed a trial or paid.

- **Free trial** → `POST /app/trial {contact}` → issues a 7-day APP key (no card,
  one per contact).
- **Buy** → `POST /app/checkout {method:"crypto"|"card"}` → real invoice via the
  licensing service; the paid key extends automatically when payment clears.
- **Pricing** → `GET /app/pricing` → the page reads the live price, trial length,
  and which pay rails are switched on.

`serve.py` proxies all three to the licensing service over `LICENSING_URL`
(default `http://127.0.0.1:8790`), so the browser stays same-origin — no CORS,
no exposed internal URL.

## Where to change things (single source of truth)

| What | Where |
|------|-------|
| **Monthly price** | `licensing/config.py` → `PRODUCTS["APP"]["price_solo"]` (currently 25) |
| **Free-trial length** | `licensing/config.py` → `APP_TRIAL_DAYS` (or env `APP_TRIAL_DAYS`; `0` = trials off) |
| **Turn trials off** | set `APP_TRIAL_DAYS=0` and restart the licensing service |
| **Sales copy / design** | `storefront/index.html` |

The page auto-reflects the price/trial numbers from `/app/pricing`, so editing
`config.py` and restarting the licensing service updates the page — no HTML edit
needed. (The numbers hard-coded in the HTML are only fallbacks for when the
pricing call can't be reached.)

## Payment rails

Both are already coded in `licensing/` and stay **hidden on the page until their
key is present** on the server:

- **Crypto (NOWPayments)** — set `NOWPAYMENTS_API_KEY` + `NOWPAYMENTS_IPN_SECRET`
  in the licensing env file. Free to set up; fits bootstrapping.
- **Card (Stripe)** — set `STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET`.

See `deploy/licensing.env.example`. With neither set, the trial still works and
the Buy buttons hide themselves.

## Deploy (VPS)

    ssh root@178.104.88.38
    cd /opt/wolf-desk
    sudo -u wolf git pull
    sudo systemctl restart wolf-desk staalwag-licensing

Then open `https://staalwag.com/store`.

## Notes / compliance

- Decision-support & education only — the page carries a risk notice and makes no
  profit promises. Keep it that way.
- Trial keys are anti-farm guarded (one per contact) but this is a soft gate;
  tighten later (email verification, rate-limit) if abuse shows up.
