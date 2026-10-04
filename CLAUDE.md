# Working with Nic — read this first, every session

Nic owns the STAALWAG / WOLF trading estate. He is a **business owner, not a
coder**. He runs commands when needed but thinks in outcomes, not code. The #1
job is to **save him time and mental load** — he has said plainly that pulling
information out of Claude has been painful. Fix that by how you communicate.

## How to communicate with Nic (the important part)

1. **Lead with the answer or the result. No preamble.** Never open with "Let me…",
   "Great question", or a recap. First line = the thing he needs.
2. **Short. One idea at a time.** Walls of text and big tables frustrate him.
   Give the next step, not the whole map. He'll ask for more if he wants it.
3. **Show, don't tell.** When something is built, *render/send the file* so he can
   SEE it (he's a visual thinker — he sends screenshots and circles things).
   Don't describe a page; show the page.
4. **Explain with one concrete, real-world example**, not abstractly. The partner
   system only clicked when it was walked through as "your mate Joe with a Telegram
   channel." Abstract + tables = confusion. A named story = understanding.
5. **When he must run something, give ONE exact copy-paste line**, and anticipate
   the gotcha before it bites (URL trailing dots, *which* window, `cd` first,
   which branch, permissions). One command, clearly, not a menu.
6. **Take ownership. Act on sensible defaults.** He wants problems *sorted*, not
   handed back as questions ("someone with the right skill sort this shit out").
   Only ask when a choice genuinely changes the outcome and is his to make
   (price, payment rail) — then keep it to one tight question.
7. **Say up front what you can't do.** e.g. this cloud container has no `ssh` and
   can't reach his VPS — tell him that immediately, don't let him discover it.
8. **Don't repeat what he already has.** No re-explaining, no re-pasting.
9. **Never correct his spelling.** He writes phonetic, Afrikaans-influenced
   English — read for intent. Glossary: *prikkel* = spark/provoke interest;
   *waist* = waste; *deamin* = daemon; *comod, comoditie* = commodity. Misspelling
   ≠ confusion; he knows exactly what he wants.
10. **He's often stressed or taking time off.** He wants it to *just work*,
    hands-off. Don't add homework. Reduce steps.

## Standing business mandates (do not violate)

- **Bootstrapping = FREE.** Always find the no-cost option while getting off the
  ground. Don't propose paid tools/services unless there's no free path.
- **The business must NOT be AI-dependent.** The money path stays deterministic;
  AI is an optional convenience, never a lifeline. Designing out AI-dependency is
  the job, not a deviation from it.
- **Never put model identifiers** (Claude/Opus/etc.) in commits, PRs, code, or
  anything pushed to a repo. Chat only.
- **Marking convention:** ✗ / X on something = *delete it*. A circle = *question or
  change it* — never delete a circled item.
- **Secrets** (`.env`, `WOLF_PASS`, `ADMIN_TOKEN`, telegram/PayPal tokens) stay
  out of git.

## Infra cheat-sheet (so you don't re-derive it)

- **VPS:** `178.104.88.38` = `staalwag.com`. Deploys run there, in HIS SSH window
  (Claude's container can't SSH). App user is `wolf`; if a pull fails on
  permissions: `sudo chown -R wolf:wolf /opt/wolf-desk` then pull.
  Deploy = `cd /opt/wolf-desk && sudo -u wolf git pull && sudo systemctl restart wolf-desk staalwag-licensing`
  **Auto-ship** (once `deploy/autoship-setup.sh` has been run): a timer ships
  whatever is merged into the live branch within 5 min, rolls back + Telegrams
  Nic if it breaks. So "merge the PR" = "it's live".
  Before going live it runs `tests/` (checkout -> payment -> activation; also
  run on every PR by GitHub). Any change to payments or licensing must keep
  them green: `python -m unittest discover -s tests`.
- **serve.py** (port 8777) host-routes: `staalwag.com`→site, `wolf.*`→WOLF desk,
  `app.*`→the app; also `/store` (storefront), `/proof` (track record).
- **Track record honesty:** MT5 account 109223212 is a MetaQuotes **demo** account.
  Its EA results go on /proof labelled "demo account", never "live"/"real"
  (`proof_labels.py` enforces it server-side; `EA_ACCOUNT_TYPE=live` in
  push_proof.py only for a real-money account).
- **Markov 18-pair bot** lives in `markov/` (Node). An old copy still posts daily via
  @Staalwag_bot (not tracked in HQ since 18 Aug); the fixed version replaces it. VPS service `markov-bot`
  (port 8783, `/etc/markov-bot.env`, one-time `deploy/markov-setup.sh`); record
  at `staalwag.com/markov/signals.json`. One post per idea, 6xATR stop, 2R,
  12h time-stop, results posted. Tests: `cd markov && npm test`.
- **Gold + VELDRIN signal desks** (repos Staalwag-desk / Veldrin-Desk) run on the VPS,
  not Railway (gone): services `staalwag-desk` (8781 -> @staalwagsignals) and
  `veldrin-desk` (8782 -> @veldrinforex), env `/etc/<desk>.env`, ledgers in
  `/var/lib/<desk>/`, Yahoo prices (no key). Setup/repair: `deploy/desks-setup.sh`.
  HQ reads `staalwag.com/desks/gold|fx/track_record.json`.
- **licensing service** (port 8790, localhost-only, behind Caddy): products/prices
  in `licensing/config.py`; admin endpoints need `X-Admin-Token` (in
  `/etc/staalwag-licensing.env`).
  Nightly backup: the licensing bot sends `licenses-<date>.db.gz` to the admin
  Telegram chat (licensing/backup.py, restore steps at its top).
- **The PC** (almost always on) runs the trading desk: `node task-runner.js`
  (the "daemon" window — fires plans every 4h + auto-publishes) and Paperclip
  (`npm exec paperclipai run`, hosts the DB on :54329). Yahoo prices work on the
  PC, are BLOCKED from Claude's cloud container.
- **The store:** `staalwag.com/store` — free 7-day trial → $14.99/mo (launch promo,
  reg $25). Crypto + PayPal pay live; card off until Stripe keys added. Partner
  banner kit at `/store/banners.html`. Partner rewards = no stacking (one window
  at a time).

## STAALCALIBUR app (key fact for updates)

- The Android app is a **TWA — a thin shell wrapping the live website.** Feature/
  content changes = deploy the site; they go live in the installed app instantly,
  **NO Play Store update.** Only touch Play Console for icon/name changes or
  Google's yearly target-API bump.
- **Brand:** STAALWAG steel logo = the app ICON everywhere (Play icon slot +
  phone home-screen). The chrome double-chevron appears ONLY in Play Store promo
  images (feature graphic + screenshots), never as the icon.
- **Ideas board / update rhythm (runs itself — Nic has no time for pings):**
  users send ideas (with a category) or private bug reports in the app. Clean
  ideas go straight on the public board (abuse auto-rejected); repeats of an
  open idea become a vote, repeats of a built one get "already in the app".
  Everyone votes 👍 (counts public, names never). Nic gets ONE Telegram message
  a week (Monday): bugs to fix + (every 2nd week, from `RELEASE_ANCHOR`) the
  top-voted ideas; big ideas ship on the 1st. Auto-ship only messages on
  failure. HQ → App: mark built (voters get "you asked, we built it"), hide.
  With the "STAALWAG Updates" channel set up (deploy/updates-channel-setup.sh;
  its own bot UPDATES_BOT_TOKEN — never mixed with signal/licensing bots),
  a Monday routine reads `GET /digest`, builds the fixes/ideas as a PR into the
  live branch, and `POST /ready` puts a "✅ Review & approve" button in the
  channel; Nic merging = approval = live in 5 min. The app never depends on it.
  Weekly-build commits carry `Ideas-Built: <ids>` / `Bugs-Fixed: <ids>` lines;
  auto-ship marks those on the board once live (voters get notified).
- **Status (Oct 2026):** v1 submitted to Play closed testing; needs 12 testers
  for 14 days (free tester-swap app, e.g. TheClosedTest) before production access.
  Opt-in link appears once Google approves the closed-test release.
  Tester sign-up page: `staalwag.com/testers` (Gmail + live x/12 bar; admin
  pinged per sign-up; `GET /admin/testers` on the licensing service gives the
  comma list to paste into Play Console). Set `PLAY_OPTIN_URL` in
  /etc/staalwag-licensing.env once the opt-in link exists.

## Dev/branch

- Push only to the designated dev branch given in the session prompt. Retry pushes
  with backoff. Commit messages: clear, no model identifiers.
