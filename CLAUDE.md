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
- **Secrets** (`.env`, `WOLF_PASS`, `ADMIN_TOKEN`, telegram tokens) stay out of git.

## Infra cheat-sheet (so you don't re-derive it)

- **VPS:** `178.104.88.38` = `staalwag.com`. Deploys run there, in HIS SSH window
  (Claude's container can't SSH). App user is `wolf`; if a pull fails on
  permissions: `sudo chown -R wolf:wolf /opt/wolf-desk` then pull.
  Deploy = `cd /opt/wolf-desk && sudo -u wolf git pull && sudo systemctl restart wolf-desk staalwag-licensing`
- **serve.py** (port 8777) host-routes: `staalwag.com`→site, `wolf.*`→WOLF desk,
  `app.*`→the app; also `/store` (storefront), `/proof` (track record).
- **licensing service** (port 8790, localhost-only, behind Caddy): products/prices
  in `licensing/config.py`; admin endpoints need `X-Admin-Token` (in
  `/etc/staalwag-licensing.env`).
- **The PC** (almost always on) runs the trading desk: `node task-runner.js`
  (the "daemon" window — fires plans every 4h + auto-publishes) and Paperclip
  (`npm exec paperclipai run`, hosts the DB on :54329). Yahoo prices work on the
  PC, are BLOCKED from Claude's cloud container.
- **The store:** `staalwag.com/store` — free 7-day trial → $9.99/mo (launch promo,
  reg $25). Crypto pay live; card off until Stripe keys added. Partner banner kit
  at `/store/banners.html`. Partner rewards = no stacking (one window at a time).

## Dev/branch

- Push only to the designated dev branch given in the session prompt. Retry pushes
  with backoff. Commit messages: clear, no model identifiers.
