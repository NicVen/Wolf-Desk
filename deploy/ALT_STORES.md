# Publishing the STAALCALIBUR Mobile App to alternative Android stores

Google Play forces Google Play Billing (15% cut) for in-app subscriptions.
These stores don't — you keep crypto/card + your own licensing, at 0% or a tiny
listing fee. You already have the signed APK (`dashboard/staalcalibur.apk`), so
listing is mostly filling in a form and uploading assets.

## Ready-made assets (in this repo, served on the site)
- **APK**: `dashboard/staalcalibur.apk`  →  https://app.staalwag.com/staalcalibur.apk
- **App icon (512×512)**: `dashboard/icon-512.png`
- **Feature graphic (1024×500)**: `dashboard/feature-graphic.png`
- **Share/hero banner (1200×630)**: `dashboard/og-staalwag.png`
- **Screenshots**: take 3–6 on your phone (home list, a consult with the chart
  + levels, the Today's Outlook sheet, the Refer & earn card). Portrait PNGs.

## Listing copy (paste into any store)

**Title:** STAALCALIBUR — Pre-trade intel

**Short description (≤80 chars):**
Pre-trade intel for FX, crypto, commodities, indices & stocks — check before you trade.

**Full description:**
> STAALCALIBUR is your pre-trade co-pilot. Open any market and get a clear read
> in seconds — what it's doing, why, where the levels are, and what's driving it
> today.
>
> • Direction chart with entry, stop and target drawn on it (structure-based
>   stops, 2:1 targets, on 1H or Daily)
> • A 0–100 score and a BUY / SELL / WATCH verdict
> • The Markov market regime (bull / bear / sideways) with a confidence gate
> • Edge validation — a deflated-Sharpe test flags real vs. noise
> • A daily outlook and live market headlines on every pair
> • Covers commodities, FX, indices, stocks and crypto
>
> Rental subscription. Educational & decision-support only — not financial
> advice. Markets carry risk; trade a demo first and never risk more than you
> can afford to lose.

**Category:** Finance   **Content rating:** everyone / adult per store rules
**Website:** https://staalwag.com   **Support:** your contact/email
**Privacy policy:** https://staalwag.com/privacy  (add a page when required)

## Where to list (no forced billing cut)

1. **Aptoide** (aptoide.com/account/dashboard) — free dev account, upload the
   APK, paste the copy + assets. Largest independent Android store.
2. **Amazon Appstore** (developer.amazon.com) — free, reaches Amazon devices +
   Windows 11 Android subsystem. Upload APK, fill listing.
3. **Samsung Galaxy Store** (seller.samsungapps.com) — free dev account, big on
   Samsung phones. Upload APK + assets.
4. **F-Droid** — only if you open-source; skip for a paid app.
5. **APKPure / Uptodown** — mirror listings for extra discovery.

## Direct download (already live, your best channel)
- **https://staalwag.com** → Download band + QR
- **https://app.staalwag.com/download** → install page + steps
- Share the QR (on the site) in videos, posts and print.

## Note on updates
Store-installed copies update through that store's review, so they lag. The APK
you host at `/staalcalibur.apk` plus the in-app "Update now" flow stay instant —
keep the hosted APK current, and treat the stores as discovery funnels.
