// WOLF Desk server client. Auth is WOLF_PASS: the server accepts ?key=<pass>
// on every gated request (serve.py `_authed`), so we just append it. Open
// endpoints (/rates, /calendar, /fx, /health) ignore the key harmlessly.

export const CLASSES = [
  { key: 'commodities', label: 'Commodities' },
  { key: 'fx', label: 'FX' },
  { key: 'indices', label: 'Indices' },
  { key: 'stocks', label: 'Stocks' },
];

export function makeClient(baseUrl, pass) {
  const base = (baseUrl || '').replace(/\/+$/, '');
  const keyParam = pass ? `key=${encodeURIComponent(pass)}` : '';

  async function getJSON(path, { timeout = 25000 } = {}) {
    const sep = path.includes('?') ? '&' : '?';
    const url = base + path + (keyParam ? sep + keyParam : '');
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), timeout);
    try {
      const res = await fetch(url, {
        headers: { Accept: 'application/json' },
        signal: ctl.signal,
      });
      if (res.status === 401) throw new Error('Auth failed — check WOLF_PASS');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      if (e.name === 'AbortError') throw new Error('Request timed out');
      throw e;
    } finally {
      clearTimeout(t);
    }
  }

  return {
    base,
    data: (cls) => getJSON(`/data?class=${cls}`),
    refresh: (cls) => getJSON(`/refresh?class=${cls}`, { timeout: 90000 }),
    news: (name) => getJSON(`/news?name=${encodeURIComponent(name)}`),
    rates: () => getJSON('/rates'),
    calendar: () => getJSON('/calendar'),
    health: () => getJSON('/health'),
  };
}

// Client-side mirror of scout/regime.market_read: majority vote across the
// class, counting ONLY regimes that clear the sample-size gate (vote flag, or
// n>=8 fallback for older payloads). Thin reads can't swing the call.
export function marketRead(opps = []) {
  const votes = { BULL: 0, BEAR: 0, SIDE: 0 };
  let counted = 0;
  for (const o of opps) {
    const r = o.regime || {};
    const s = r.state;
    if (!(s in votes)) continue;
    let v = r.vote;
    if (v == null) v = (r.n || 0) >= 8;
    if (!v) continue;
    votes[s] += 1;
    counted += 1;
  }
  if (!counted) return { state: null, votes, counted: 0 };
  const state = Object.keys(votes).reduce((a, b) => (votes[b] > votes[a] ? b : a));
  return { state, votes, counted };
}

// Pre-trade checklist (ARCHITECTURE.md §16 step 5). Returns rows the case file
// renders as ✓ / ✗ / — so the human gates the manual trade on hard criteria.
export function preTradeChecks(o, market, newsTilt) {
  const r = o.regime || {};
  const a = o.analysis || {};
  const verdict = a.verdict || '';
  const side = verdict.startsWith('BUY') ? 'BULL' : verdict === 'SELL' ? 'BEAR' : null;
  const atr = o.atr_pct;

  const rows = [];

  // 1. verdict direction agrees with the market weather
  rows.push({
    label: 'Aligns with market regime',
    ok: market.state == null ? null : side != null && side === market.state,
    note: market.state == null
      ? 'no market read today'
      : `${verdict || 'WATCH'} vs market ${market.state}`,
  });

  // 2. regime is well-sampled and sticky enough to lean on
  const persistOk = !!r.vote && r.persist != null && r.persist >= 0.6;
  rows.push({
    label: 'Regime solid & sticky (voting, persist ≥ 60%)',
    ok: persistOk,
    note: r.vote
      ? `n=${r.n}, persist ${r.persist != null ? Math.round(r.persist * 100) + '%' : '—'}, ${r.confidence}`
      : `thin (n=${r.n || 0}) — excluded from vote`,
  });

  // 3. volatility in the tradeable band
  const atrOk = atr != null && atr >= 0.5 && atr <= 3.0;
  rows.push({
    label: 'Volatility tradeable (ATR 0.5–3%)',
    ok: atrOk,
    note: atr != null ? `ATR ${atr}%` : 'no data',
  });

  // 4. score conviction
  rows.push({
    label: 'Conviction ≥ Moderate (score ≥ 50)',
    ok: o.score >= 50,
    note: `score ${o.score} · ${a.conviction || '—'}`,
  });

  // 5. DSR — is the move statistically real?
  const v = o.validation || {};
  if (v.dsr != null) {
    rows.push({
      label: 'Move statistically real (DSR ≥ 90%)',
      ok: v.dsr >= 0.9,
      note: `DSR ${Math.round(v.dsr * 100)}% · ${v.label}`,
    });
  }

  // 6. news does not contradict the chart (only once news is loaded)
  if (newsTilt) {
    const contradict =
      (newsTilt === 'bullish news flow' && verdict === 'SELL') ||
      (newsTilt === 'bearish news flow' && verdict.startsWith('BUY'));
    const informative = newsTilt.includes('bullish') || newsTilt.includes('bearish');
    rows.push({
      label: 'News does not contradict the chart',
      ok: informative ? !contradict : null,
      note: newsTilt,
    });
  }

  const hard = rows.filter((x) => x.ok === false).length;
  return { rows, side, cleared: hard === 0 };
}
