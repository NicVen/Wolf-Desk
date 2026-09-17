// STAALWAG steel palette — mirrors the web dashboard (dark, trading-floor look).
export const C = {
  bg: '#0a0e15',
  card: '#131a26',
  cardHi: '#18212f',
  border: '#1e2a3a',
  text: '#cdd6df',
  muted: '#7d8a9c',
  faint: '#4d5a6c',
  steel: '#8aa0b4',
  accent: '#6ea8fe',

  bull: '#2ecc71',
  bear: '#ff5a5a',
  side: '#f5b301',

  // verdict colors
  buy: '#2ecc71',
  buyWeak: '#8bd6a8',
  sell: '#ff5a5a',
  watch: '#f5b301',

  ok: '#2ecc71',
  no: '#ff5a5a',
  na: '#7d8a9c',
};

export const REGIME_ICON = { BULL: '🟢', BEAR: '🔴', SIDE: '🟡' };

export function regimeColor(state) {
  return state === 'BULL' ? C.bull : state === 'BEAR' ? C.bear : state === 'SIDE' ? C.side : C.muted;
}

export function verdictColor(verdict = '') {
  if (verdict === 'SELL') return C.sell;
  if (verdict === 'WATCH') return C.watch;
  if (verdict.startsWith('BUY (weak')) return C.buyWeak;
  if (verdict.startsWith('BUY')) return C.buy;
  return C.muted;
}
