import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { C, REGIME_ICON, regimeColor, verdictColor } from '../theme';

export function Pill({ text, color = C.muted, bg }) {
  return (
    <View style={[styles.pill, { backgroundColor: bg || 'rgba(255,255,255,0.05)', borderColor: color }]}>
      <Text style={[styles.pillTxt, { color }]}>{text}</Text>
    </View>
  );
}

export function VerdictChip({ verdict }) {
  const color = verdictColor(verdict);
  return <Pill text={verdict || 'WATCH'} color={color} bg={color + '22'} />;
}

// Regime tag that respects the sample-size gate: thin (non-voting) reads are
// shown but clearly marked; medium confidence gets a ⚠.
export function RegimeChip({ regime }) {
  const r = regime || {};
  const st = r.state;
  if (!st) return <Pill text="no regime" color={C.faint} />;
  const color = regimeColor(st);
  const icon = REGIME_ICON[st] || '';
  let vote = r.vote;
  if (vote == null) vote = (r.n || 0) >= 8;

  if (!vote) {
    return <Pill text={`${icon} ${st} · thin n=${r.n || 0}`} color={C.faint} bg="rgba(255,255,255,0.04)" />;
  }
  const persist = r.persist != null ? `${Math.round(r.persist * 100)}% stay` : '—';
  const warn = r.confidence === 'medium' ? ' ⚠' : '';
  return <Pill text={`${icon} ${st} · ${persist}${warn}`} color={color} bg={color + '1e'} />;
}

const VAL_SHORT = {
  'very likely real': 'real',
  'likely real': 'likely',
  unproven: 'unproven',
  'indistinguishable from noise': 'noise',
  'no directional edge': '',
  'too little data': 'low data',
};
function valColor(lab) {
  if (lab === 'very likely real') return C.bull;
  if (lab === 'likely real') return '#9bd6a0';
  if (lab === 'unproven') return C.side;
  if (lab === 'indistinguishable from noise') return C.bear;
  return C.faint;
}
// DSR "is the move real or noise?" chip. full=true → % + full label.
export function ValidationChip({ validation, full }) {
  const v = validation || {};
  const lab = v.label;
  if (!lab) return null;
  const short = VAL_SHORT[lab];
  if (short === '') return null; // hide "no directional edge" in compact rows
  const color = valColor(lab);
  const pct = v.dsr != null ? `${Math.round(v.dsr * 100)}% ` : '';
  const text = `DSR ${pct}· ${full ? lab : short || lab}`;
  return <Pill text={text} color={color} bg={color + '1e'} />;
}

export function ScoreBar({ score = 0, max = 100 }) {
  const pct = Math.max(0, Math.min(100, (score / max) * 100));
  const color = score >= 65 ? C.bull : score >= 50 ? '#9bd6a0' : score >= 40 ? C.side : C.muted;
  return (
    <View style={styles.barWrap}>
      <View style={styles.barBg}>
        <View style={[styles.barFill, { width: `${pct}%`, backgroundColor: color }]} />
      </View>
      <Text style={[styles.barTxt, { color }]}>{score}</Text>
    </View>
  );
}

// Horizontal breakdown of the five score components, each against its cap.
const CAPS = { catalyst: 25, trend: 25, position: 20, supply: 20, volfit: 10 };
const LBL = { catalyst: 'Catalyst', trend: 'Trend', position: 'Position', supply: 'Supply', volfit: 'Vol-fit' };
export function Breakdown({ breakdown = {} }) {
  return (
    <View style={{ gap: 6 }}>
      {Object.keys(CAPS).map((k) => {
        const val = breakdown[k] || 0;
        const cap = CAPS[k];
        const pct = Math.max(0, Math.min(100, (val / cap) * 100));
        return (
          <View key={k} style={styles.bdRow}>
            <Text style={styles.bdLabel}>{LBL[k]}</Text>
            <View style={styles.bdBarBg}>
              <View style={[styles.bdBarFill, { width: `${pct}%` }]} />
            </View>
            <Text style={styles.bdVal}>{val}/{cap}</Text>
          </View>
        );
      })}
    </View>
  );
}

export function SectionLabel({ children }) {
  return <Text style={styles.section}>{children}</Text>;
}

const styles = StyleSheet.create({
  pill: {
    paddingHorizontal: 9,
    paddingVertical: 3,
    borderRadius: 6,
    borderWidth: 1,
    alignSelf: 'flex-start',
  },
  pillTxt: { fontSize: 12, fontWeight: '700', letterSpacing: 0.3 },

  barWrap: { flexDirection: 'row', alignItems: 'center', gap: 8, flex: 1 },
  barBg: { flex: 1, height: 7, borderRadius: 4, backgroundColor: 'rgba(255,255,255,0.07)', overflow: 'hidden' },
  barFill: { height: 7, borderRadius: 4 },
  barTxt: { width: 38, textAlign: 'right', fontWeight: '800', fontSize: 13 },

  bdRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  bdLabel: { color: C.muted, width: 64, fontSize: 12 },
  bdBarBg: { flex: 1, height: 6, borderRadius: 3, backgroundColor: 'rgba(255,255,255,0.07)', overflow: 'hidden' },
  bdBarFill: { height: 6, borderRadius: 3, backgroundColor: C.accent },
  bdVal: { color: C.text, width: 48, textAlign: 'right', fontSize: 11, fontVariant: ['tabular-nums'] },

  section: { color: C.steel, fontSize: 12, fontWeight: '800', letterSpacing: 1, textTransform: 'uppercase', marginBottom: 8 },
});
