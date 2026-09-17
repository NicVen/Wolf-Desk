import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  View, Text, StyleSheet, FlatList, Pressable, TextInput,
  ActivityIndicator, RefreshControl, ScrollView, KeyboardAvoidingView, Platform,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { C, REGIME_ICON, regimeColor } from './src/theme';
import { CLASSES, makeClient, marketRead } from './src/api';
import { loadSettings, saveSettings, DEFAULT_URL } from './src/storage';
import { VerdictChip, RegimeChip, ScoreBar } from './src/components/ui';
import CaseFile from './src/components/CaseFile';

export default function App() {
  const [settings, setSettings] = useState(null); // {baseUrl, pass}
  const [showSettings, setShowSettings] = useState(false);

  const [cls, setCls] = useState('fx');
  const [payload, setPayload] = useState(null); // {generated, opportunities}
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);

  const client = useMemo(
    () => (settings ? makeClient(settings.baseUrl, settings.pass) : null),
    [settings]
  );

  useEffect(() => {
    loadSettings().then((s) => {
      setSettings(s);
      if (!s.pass) setShowSettings(true);
    });
  }, []);

  const fetchClass = useCallback(
    async (which, { silent } = {}) => {
      if (!client) return;
      if (!silent) setLoading(true);
      setError(null);
      try {
        const j = await client.data(which);
        setPayload(j);
      } catch (e) {
        setError(e.message);
        setPayload(null);
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [client]
  );

  useEffect(() => {
    if (client && !showSettings) fetchClass(cls);
  }, [client, cls, showSettings, fetchClass]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    fetchClass(cls, { silent: true });
  }, [cls, fetchClass]);

  // Server-side full re-run of the pipeline for this class (slower).
  const onHardRefresh = useCallback(async () => {
    if (!client) return;
    setLoading(true); setError(null);
    try {
      const j = await client.refresh(cls);
      setPayload(j);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [client, cls]);

  const opps = (payload && payload.opportunities) || [];
  const market = useMemo(() => marketRead(opps), [opps]);

  if (!settings) {
    return (
      <View style={[styles.screen, styles.center]}>
        <ActivityIndicator color={C.accent} />
      </View>
    );
  }

  if (showSettings) {
    return (
      <SettingsScreen
        initial={settings}
        onSave={async (s) => {
          await saveSettings(s);
          setSettings(s);
          setShowSettings(false);
        }}
        canCancel={!!settings.pass}
        onCancel={() => setShowSettings(false)}
      />
    );
  }

  return (
    <View style={styles.screen}>
      <StatusBar style="light" />

      {/* header */}
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={styles.brand}>WOLF <Text style={{ color: C.steel }}>DESK</Text></Text>
          <Text style={styles.tagline}>Read the market like a wolf.</Text>
        </View>
        <Pressable onPress={() => setShowSettings(true)} hitSlop={10} style={styles.gear}>
          <Text style={{ color: C.muted, fontSize: 18 }}>⚙</Text>
        </Pressable>
      </View>

      {/* market weather banner (this class) */}
      <MarketBanner market={market} clsLabel={labelFor(cls)} generated={payload && payload.generated} />

      {/* class tabs */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.tabs} contentContainerStyle={{ gap: 8, paddingHorizontal: 12 }}>
        {CLASSES.map((c) => (
          <Pressable key={c.key} onPress={() => setCls(c.key)} style={[styles.tab, cls === c.key && styles.tabActive]}>
            <Text style={[styles.tabTxt, cls === c.key && styles.tabTxtActive]}>{c.label}</Text>
          </Pressable>
        ))}
      </ScrollView>

      {error && (
        <View style={styles.errorBox}>
          <Text style={styles.errorTxt}>{error}</Text>
          <Pressable onPress={() => fetchClass(cls)}><Text style={styles.retry}>Retry</Text></Pressable>
        </View>
      )}

      {loading && !refreshing ? (
        <View style={[styles.center, { flex: 1 }]}><ActivityIndicator color={C.accent} /></View>
      ) : (
        <FlatList
          data={opps}
          keyExtractor={(o) => o.name}
          contentContainerStyle={{ padding: 12, paddingBottom: 40, gap: 10 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={C.accent} />}
          renderItem={({ item }) => <OppCard opp={item} onPress={() => setSelected(item)} />}
          ListFooterComponent={
            opps.length ? (
              <Pressable onPress={onHardRefresh} style={styles.rerun}>
                <Text style={styles.rerunTxt}>↻ Re-run pipeline (live prices)</Text>
              </Pressable>
            ) : null
          }
          ListEmptyComponent={!loading && <Text style={styles.empty}>No opportunities loaded.</Text>}
        />
      )}

      {selected && (
        <CaseFile opp={selected} market={market} client={client} onClose={() => setSelected(null)} />
      )}
    </View>
  );
}

function labelFor(key) {
  const c = CLASSES.find((x) => x.key === key);
  return c ? c.label : key;
}

function MarketBanner({ market, clsLabel, generated }) {
  const color = regimeColor(market.state);
  const v = market.votes || {};
  return (
    <View style={[styles.banner, { borderColor: color + '55' }]}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        <Text style={{ fontSize: 16 }}>{REGIME_ICON[market.state] || '⚪'}</Text>
        <Text style={styles.bannerState}>
          {clsLabel} regime: <Text style={{ color }}>{market.state || 'No read'}</Text>
        </Text>
      </View>
      <Text style={styles.bannerVotes}>
        {market.state
          ? `Bull ${v.BULL} · Bear ${v.BEAR} · Side ${v.SIDE}  ·  ${market.counted} voted`
          : 'Not enough well-sampled regimes to call it'}
      </Text>
      {!!generated && <Text style={styles.bannerGen}>data {generated}</Text>}
    </View>
  );
}

function OppCard({ opp, onPress }) {
  const a = opp.analysis || {};
  return (
    <Pressable onPress={onPress} style={styles.card}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <Text style={styles.oppName}>{opp.name}</Text>
        <Text style={styles.oppCat}>{opp.category}</Text>
        <View style={{ flex: 1 }} />
        <VerdictChip verdict={a.verdict} />
      </View>
      <ScoreBar score={opp.score} />
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
        <RegimeChip regime={opp.regime} />
        <Text style={styles.trend}>{opp.trend_desc}</Text>
      </View>
    </Pressable>
  );
}

function SettingsScreen({ initial, onSave, canCancel, onCancel }) {
  const [baseUrl, setBaseUrl] = useState(initial.baseUrl || DEFAULT_URL);
  const [pass, setPass] = useState(initial.pass || '');
  const [testing, setTesting] = useState(false);
  const [msg, setMsg] = useState(null);

  const test = async () => {
    setTesting(true); setMsg(null);
    try {
      const c = makeClient(baseUrl, pass);
      const j = await c.data('fx');
      const n = (j.opportunities || []).length;
      setMsg({ ok: true, text: `Connected — ${n} FX opportunities loaded.` });
    } catch (e) {
      setMsg({ ok: false, text: e.message });
    } finally {
      setTesting(false);
    }
  };

  return (
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.screen}>
      <StatusBar style="light" />
      <ScrollView contentContainerStyle={{ padding: 20, paddingTop: 64, gap: 16 }}>
        <Text style={styles.brand}>WOLF <Text style={{ color: C.steel }}>DESK</Text></Text>
        <Text style={styles.settingsIntro}>
          Point the app at your WOLF server and enter your access key (WOLF_PASS).
          The key is sent as <Text style={{ color: C.accent }}>?key=</Text> on each request and stored on this device only.
        </Text>

        <Field label="Server URL">
          <TextInput
            value={baseUrl}
            onChangeText={setBaseUrl}
            placeholder={DEFAULT_URL}
            placeholderTextColor={C.faint}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            style={styles.input}
          />
        </Field>

        <Field label="WOLF_PASS">
          <TextInput
            value={pass}
            onChangeText={setPass}
            placeholder="your access key"
            placeholderTextColor={C.faint}
            autoCapitalize="none"
            autoCorrect={false}
            secureTextEntry
            style={styles.input}
          />
        </Field>

        <Pressable onPress={test} style={[styles.btn, styles.btnGhost]} disabled={testing}>
          {testing ? <ActivityIndicator color={C.accent} /> : <Text style={styles.btnGhostTxt}>Test connection</Text>}
        </Pressable>

        {msg && (
          <Text style={{ color: msg.ok ? C.ok : C.no, fontSize: 13 }}>{msg.text}</Text>
        )}

        <Pressable onPress={() => onSave({ baseUrl: baseUrl.trim(), pass: pass.trim() })} style={[styles.btn, styles.btnPrimary]}>
          <Text style={styles.btnPrimaryTxt}>Save & enter desk</Text>
        </Pressable>

        {canCancel && (
          <Pressable onPress={onCancel}><Text style={styles.cancel}>Cancel</Text></Pressable>
        )}

        <Text style={styles.disclaimer}>
          Decision-support only. Every read is a mechanical view of the data, not financial advice.
          Verify before risking capital.
        </Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function Field({ label, children }) {
  return (
    <View style={{ gap: 6 }}>
      <Text style={styles.fieldLabel}>{label}</Text>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: C.bg },
  center: { alignItems: 'center', justifyContent: 'center' },

  header: {
    paddingTop: 56, paddingBottom: 12, paddingHorizontal: 16,
    flexDirection: 'row', alignItems: 'center',
    borderBottomWidth: 1, borderBottomColor: C.border, backgroundColor: C.card,
  },
  brand: { color: C.text, fontSize: 24, fontWeight: '900', letterSpacing: 1 },
  tagline: { color: C.muted, fontSize: 12, fontStyle: 'italic', marginTop: 1 },
  gear: { width: 36, height: 36, alignItems: 'center', justifyContent: 'center' },

  banner: {
    margin: 12, marginBottom: 6, padding: 12, borderRadius: 12,
    backgroundColor: C.card, borderWidth: 1, gap: 3,
  },
  bannerState: { color: C.text, fontSize: 15, fontWeight: '800' },
  bannerVotes: { color: C.muted, fontSize: 12 },
  bannerGen: { color: C.faint, fontSize: 11 },

  tabs: { maxHeight: 46, marginBottom: 2 },
  tab: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 20, backgroundColor: C.card, borderWidth: 1, borderColor: C.border },
  tabActive: { backgroundColor: C.accent + '22', borderColor: C.accent },
  tabTxt: { color: C.muted, fontWeight: '700', fontSize: 13 },
  tabTxtActive: { color: C.accent },

  card: { backgroundColor: C.card, borderRadius: 14, borderWidth: 1, borderColor: C.border, padding: 14 },
  oppName: { color: C.text, fontSize: 17, fontWeight: '800' },
  oppCat: { color: C.faint, fontSize: 12 },
  trend: { color: C.muted, fontSize: 12, fontStyle: 'italic' },

  rerun: { marginTop: 6, padding: 12, alignItems: 'center' },
  rerunTxt: { color: C.accent, fontSize: 13, fontWeight: '700' },
  empty: { color: C.muted, textAlign: 'center', marginTop: 40 },

  errorBox: { margin: 12, marginTop: 4, padding: 12, borderRadius: 10, backgroundColor: C.sell + '18', borderWidth: 1, borderColor: C.sell + '55', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  errorTxt: { color: C.sell, fontSize: 12, flex: 1 },
  retry: { color: C.accent, fontWeight: '800', marginLeft: 12 },

  settingsIntro: { color: C.muted, fontSize: 13, lineHeight: 19 },
  fieldLabel: { color: C.steel, fontSize: 12, fontWeight: '700', letterSpacing: 0.5 },
  input: { backgroundColor: C.card, borderWidth: 1, borderColor: C.border, borderRadius: 10, padding: 12, color: C.text, fontSize: 15 },

  btn: { padding: 14, borderRadius: 10, alignItems: 'center' },
  btnPrimary: { backgroundColor: C.accent },
  btnPrimaryTxt: { color: '#08111f', fontWeight: '900', fontSize: 15 },
  btnGhost: { borderWidth: 1, borderColor: C.border, backgroundColor: C.card },
  btnGhostTxt: { color: C.accent, fontWeight: '800' },
  cancel: { color: C.muted, textAlign: 'center', fontSize: 14 },
  disclaimer: { color: C.faint, fontSize: 11, lineHeight: 16, marginTop: 8, fontStyle: 'italic' },
});
