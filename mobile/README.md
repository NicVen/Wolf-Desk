# WOLF Desk — mobile companion (Expo / React Native)

A standalone phone app to **consult the desk before you place a trade manually**.
It reads the WOLF server's JSON API and renders, per asset class:

- a **market-weather banner** (Markov regime majority vote, thin reads excluded);
- a **ranked opportunity list** — verdict, 0–100 score, regime confidence chip,
  trend read;
- a **case file** on tap — verdict + conviction, price reasoning, the 5-component
  score breakdown, bull vs bear, a **pre-trade checklist**, on-demand **news**
  (shown as context only), and broker/prop-firm coverage.

It is decision-support only. Every read is a mechanical view of the data, **not
financial advice** — verify before risking capital.

## Auth — WOLF_PASS

The app authenticates with `WOLF_PASS`. The server (`serve.py`) accepts
`?key=<WOLF_PASS>` on every gated request, so the app appends it to each call.
Set `WOLF_PASS` in the server's environment, then enter the same value in the
app's Settings screen. The key is stored on-device (AsyncStorage) only.

## Run it

Prerequisites: Node 18+, and the **Expo Go** app on your phone (or an
iOS Simulator / Android emulator).

```bash
cd mobile
npm install          # or: yarn
npx expo start       # opens the Metro dev server + QR code
```

- **Phone:** scan the QR code with Expo Go (same Wi-Fi as your computer).
- **Simulator/emulator:** press `i` (iOS) or `a` (Android) in the Expo terminal.

On first launch, enter your **Server URL** (defaults to the Railway URL) and your
**WOLF_PASS**, tap **Test connection**, then **Save & enter desk**.

> If versions drift, run `npx expo install --fix` to align native deps with the
> installed Expo SDK.

## Build a standalone app (optional)

Use EAS to produce installable binaries (no Expo Go needed):

```bash
npm i -g eas-cli
eas login
eas build -p android --profile preview     # APK you can sideload
eas build -p ios --profile preview          # needs an Apple developer account
```

## Endpoints used

| Call | Endpoint | Auth |
|---|---|---|
| ranked list | `GET /data?class=<commodities\|fx\|indices\|stocks>` | `?key=` |
| live re-run | `GET /refresh?class=<class>` | `?key=` |
| headlines | `GET /news?name=<Instrument>` | `?key=` |

The market-weather vote is computed client-side (`src/api.js → marketRead`),
mirroring `scout/regime.market_read` including the sample-size gate (`n ≥ 8` to
vote), so thin regimes never swing the call.

## Layout

```
mobile/
  App.js                     settings gate, market banner, tabs, ranked list
  index.js                   Expo entry
  src/
    api.js                   server client + marketRead + preTradeChecks
    theme.js                 STAALWAG steel palette + regime/verdict colors
    storage.js               on-device settings (URL + WOLF_PASS)
    components/
      ui.js                  RegimeChip, VerdictChip, ScoreBar, Breakdown
      CaseFile.js            the per-instrument case-file modal
```

### Notes

- **News is context, never a score input** — the app renders the tilt separately
  and, in the checklist, only flags when headlines *contradict* the chart. It can
  never flip a BUY to a WATCH (matches the engine's design).
- **Native target.** `expo start --web` may hit CORS (the server sets no CORS
  headers); iOS/Android have no such restriction.
