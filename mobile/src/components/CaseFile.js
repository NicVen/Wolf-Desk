import React, { useEffect, useState } from 'react';
import {
  Modal, View, Text, ScrollView, Pressable, StyleSheet,
  ActivityIndicator, Linking,
} from 'react-native';
import { C } from '../theme';
import { VerdictChip, RegimeChip, ValidationChip, Breakdown, SectionLabel } from './ui';
import { preTradeChecks } from '../api';

function Row({ children, style }) {
  return <View style={[{ flexDirection: 'row', alignItems: 'center', gap: 8 }, style]}>{children}</View>;
}

function Check({ row }) {
  const mark = row.ok === true ? '✓' : row.ok === false ? '✗' : '—';
  const color = row.ok === true ? C.ok : row.ok === false ? C.no : C.na;
  return (
    <Row style={{ alignItems: 'flex-start', marginBottom: 8 }}>
      <Text style={{ color, fontWeight: '900', width: 18, fontSize: 15 }}>{mark}</Text>
      <View style={{ flex: 1 }}>
        <Text style={{ color: C.text, fontSize: 13, fontWeight: '600' }}>{row.label}</Text>
        <Text style={{ color: C.muted, fontSize: 12, marginTop: 1 }}>{row.note}</Text>
      </View>
    </Row>
  );
}

export default function CaseFile({ opp, market, client, onClose }) {
  const [news, setNews] = useState(null); // {news:[], tilt}
  const [newsLoading, setNewsLoading] = useState(false);
  const [newsErr, setNewsErr] = useState(null);

  useEffect(() => {
    setNews(null); setNewsErr(null);
    if (!opp || !client) return;
    let alive = true;
    setNewsLoading(true);
    client.news(opp.name)
      .then((j) => { if (alive) setNews(j); })
      .catch((e) => { if (alive) setNewsErr(e.message); })
      .finally(() => { if (alive) setNewsLoading(false); });
    return () => { alive = false; };
  }, [opp, client]);

  if (!opp) return null;
  const a = opp.analysis || {};
  const checks = preTradeChecks(opp, market, news && news.tilt);

  return (
    <Modal visible animationType="slide" onRequestClose={onClose} transparent={false}>
      <View style={styles.screen}>
        <Row style={styles.header}>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>{opp.name}</Text>
            <Text style={styles.sub}>{opp.category} · {opp.ticker}</Text>
          </View>
          <Pressable onPress={onClose} hitSlop={12} style={styles.close}>
            <Text style={{ color: C.text, fontSize: 22, lineHeight: 22 }}>×</Text>
          </Pressable>
        </Row>

        <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 48, gap: 18 }}>
          {/* verdict + regime */}
          <Row style={{ flexWrap: 'wrap', gap: 8 }}>
            <VerdictChip verdict={a.verdict} />
            <RegimeChip regime={opp.regime} />
            <ValidationChip validation={opp.validation} />
            {!!a.conviction && (
              <Text style={{ color: C.muted, fontSize: 13, alignSelf: 'center' }}>
                conviction {a.conviction}
              </Text>
            )}
          </Row>

          {!!a.summary && <Text style={styles.summary}>{a.summary}</Text>}

          {/* DSR — is the move real, or noise? (label only, never scored) */}
          {!!(opp.validation && opp.validation.label) && (
            <View style={styles.card}>
              <SectionLabel>Validation — is the move real?</SectionLabel>
              <Row style={{ flexWrap: 'wrap', gap: 8 }}>
                <ValidationChip validation={opp.validation} full />
                {opp.validation.sr != null && (
                  <Text style={{ color: C.muted, fontSize: 12, alignSelf: 'center' }}>
                    Sharpe/bar {opp.validation.sr} · n={opp.validation.n} · trials {opp.validation.trials || '—'}
                  </Text>
                )}
              </Row>
              <Text style={styles.body}>
                Deflated Sharpe: probability the move's risk-adjusted drift (in the verdict's
                direction) is real rather than noise, after deflating for the {opp.validation.trials || '—'}{' '}
                markets scanned. A label on the move, not a strategy backtest — it never changes the
                score or the verdict.
              </Text>
            </View>
          )}

          {/* pre-trade checklist */}
          <View style={styles.card}>
            <Row style={{ justifyContent: 'space-between', marginBottom: 10 }}>
              <SectionLabel>Pre-trade checklist</SectionLabel>
              <Text style={{ color: checks.cleared ? C.ok : C.watch, fontWeight: '800', fontSize: 12 }}>
                {checks.cleared ? 'ALL CLEAR' : 'CAUTION'}
              </Text>
            </Row>
            {checks.rows.map((r, i) => <Check key={i} row={r} />)}
            <Text style={styles.disclaim}>
              Mechanical read of the data — not financial advice. You place the trade.
            </Text>
          </View>

          {/* score breakdown */}
          <View style={styles.card}>
            <SectionLabel>Score {opp.score}/100</SectionLabel>
            <Breakdown breakdown={opp.breakdown} />
            {!!a.score_reasoning && <Text style={styles.body}>{a.score_reasoning}</Text>}
          </View>

          {/* price reasoning */}
          <View style={styles.card}>
            <SectionLabel>Price</SectionLabel>
            <Row style={{ flexWrap: 'wrap', gap: 14, marginBottom: 8 }}>
              <Metric label="Last" value={opp.price} />
              <Metric label="MA20" value={opp.ma20} />
              <Metric label="MA50" value={opp.ma50} />
              <Metric label="Mom 20" value={opp.mom20 != null ? `${opp.mom20}%` : '—'} />
              <Metric label="ATR" value={opp.atr_pct != null ? `${opp.atr_pct}%` : '—'} />
            </Row>
            {!!a.price_reasoning && <Text style={styles.body}>{a.price_reasoning}</Text>}
          </View>

          {/* bull / bear */}
          <View style={styles.card}>
            <SectionLabel>Bull vs Bear</SectionLabel>
            <Text style={[styles.caseHead, { color: C.bull }]}>Bull</Text>
            {(a.bull || []).length ? a.bull.map((t, i) => (
              <Text key={i} style={styles.caseLine}>• {t}</Text>
            )) : <Text style={styles.caseLine}>—</Text>}
            <Text style={[styles.caseHead, { color: C.bear, marginTop: 10 }]}>Bear</Text>
            {(a.bear || []).length ? a.bear.map((t, i) => (
              <Text key={i} style={styles.caseLine}>• {t}</Text>
            )) : <Text style={styles.caseLine}>—</Text>}
          </View>

          {/* news — surfaced separately as context (never folded into score) */}
          <View style={styles.card}>
            <Row style={{ justifyContent: 'space-between', marginBottom: 8 }}>
              <SectionLabel>News (context)</SectionLabel>
              {news && !!news.tilt && (
                <Text style={{ color: tiltColor(news.tilt), fontSize: 12, fontWeight: '700' }}>
                  {news.tilt}
                </Text>
              )}
            </Row>
            {newsLoading && <ActivityIndicator color={C.accent} />}
            {newsErr && <Text style={styles.body}>Couldn't load news: {newsErr}</Text>}
            {news && (news.news || []).length === 0 && !newsLoading && (
              <Text style={styles.body}>No recent headlines.</Text>
            )}
            {news && (news.news || []).map((h, i) => (
              <Pressable key={i} onPress={() => h.link && Linking.openURL(h.link)} style={{ marginBottom: 8 }}>
                <Text style={styles.newsTitle}>{h.title}</Text>
                <Text style={styles.newsMeta}>{[h.source, h.date].filter(Boolean).join(' · ')}</Text>
              </Pressable>
            ))}
            <Text style={styles.disclaim}>
              A keyword tilt, not sentiment analysis — a cross-check, not a score input.
            </Text>
          </View>

          {/* coverage */}
          <View style={styles.card}>
            <SectionLabel>Where to trade it ({(opp.coverage || []).length})</SectionLabel>
            {(opp.coverage || []).map((v, i) => (
              <View key={i} style={styles.covRow}>
                <Text style={styles.covName}>
                  {v.name} <Text style={{ color: C.faint }}>· {v.type}</Text>
                </Text>
                <Text style={styles.covLev}>{v.leverage}</Text>
                {!!v.notes && <Text style={styles.covNotes}>{v.notes}</Text>}
              </View>
            ))}
          </View>
        </ScrollView>
      </View>
    </Modal>
  );
}

function Metric({ label, value }) {
  return (
    <View>
      <Text style={{ color: C.faint, fontSize: 11 }}>{label}</Text>
      <Text style={{ color: C.text, fontSize: 15, fontWeight: '700' }}>{value == null ? '—' : String(value)}</Text>
    </View>
  );
}

function tiltColor(tilt = '') {
  if (tilt.includes('bullish')) return C.bull;
  if (tilt.includes('bearish')) return C.bear;
  return C.muted;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: C.bg },
  header: {
    paddingTop: 54, paddingBottom: 14, paddingHorizontal: 16,
    borderBottomWidth: 1, borderBottomColor: C.border, backgroundColor: C.card,
  },
  title: { color: C.text, fontSize: 22, fontWeight: '900' },
  sub: { color: C.muted, fontSize: 13, marginTop: 2 },
  close: { width: 34, height: 34, borderRadius: 17, backgroundColor: C.cardHi, alignItems: 'center', justifyContent: 'center' },

  summary: { color: C.text, fontSize: 15, lineHeight: 21, fontWeight: '600' },
  card: { backgroundColor: C.card, borderRadius: 14, borderWidth: 1, borderColor: C.border, padding: 14, gap: 6 },
  body: { color: C.muted, fontSize: 13, lineHeight: 19, marginTop: 6 },
  disclaim: { color: C.faint, fontSize: 11, fontStyle: 'italic', marginTop: 8 },

  caseHead: { fontSize: 12, fontWeight: '800', letterSpacing: 0.5 },
  caseLine: { color: C.text, fontSize: 13, lineHeight: 19, marginTop: 3 },

  newsTitle: { color: C.text, fontSize: 13, fontWeight: '600', lineHeight: 18 },
  newsMeta: { color: C.faint, fontSize: 11, marginTop: 1 },

  covRow: { paddingVertical: 6, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: C.border },
  covName: { color: C.text, fontSize: 13, fontWeight: '700' },
  covLev: { color: C.accent, fontSize: 12, marginTop: 1 },
  covNotes: { color: C.muted, fontSize: 11, marginTop: 1 },
});
