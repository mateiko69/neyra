import React, { useEffect, useState } from 'react';
import { SafeAreaView, Text, View, TextInput, Pressable, ScrollView } from 'react-native';

import { apiFetch } from "./src/api";
import { debugEnvLog, validateEnv, API_URL, WS_URL } from "./src/config/env";
import { tx } from "./src/uiStrings";

const theme = {
  bg: '#0f1115',
  panel: '#141826',
  text: 'rgba(255,255,255,0.92)',
  muted: 'rgba(255,255,255,0.68)',
  stroke: 'rgba(255,255,255,0.08)',
  primary: '#7C5CFF',
  accent: '#22F3FF',
  radius: 18,
};

function wsStatusLabel(status) {
  const key = `mobile.ws.status.${status}`;
  const v = tx(key);
  return v === key ? status : v;
}

export default function App() {
  const [email, setEmail] = useState('taras@example.com');
  const [password, setPassword] = useState('password123');
  const [token, setToken] = useState('');
  const [screen, setScreen] = useState('discover'); // discover | matches | chat | premium
  const [cards, setCards] = useState([]);
  const [matches, setMatches] = useState([]);
  const [subscription, setSubscription] = useState(null);
  const [error, setError] = useState("");
  const [loadingFeed, setLoadingFeed] = useState(false);
  const [loadingMatches, setLoadingMatches] = useState(false);
  const [loadingSub, setLoadingSub] = useState(false);
  const [configWarnings, setConfigWarnings] = useState([]);
  const [wsStatus, setWsStatus] = useState("disconnected"); // disconnected | connecting | connected | error
  const [wsError, setWsError] = useState("");

  async function login() {
    try {
      setError("");
      const data = await apiFetch("/auth/login", { method: "POST", body: { email, password } });
      setToken(data.access_token);
    } catch (e) {
      if (typeof __DEV__ !== "undefined" && __DEV__) {
        // eslint-disable-next-line no-console
        console.log("[NEYRA] login failed", e);
      }
      setError(tx("mobile.error.login"));
    }
  }

  async function loadFeed() {
    if (!token) return;
    try {
      setLoadingFeed(true);
      const data = await apiFetch("/discover/feed", { token });
      setCards(data || []);
    } catch (e) {
      setError(tx("mobile.error.discover"));
    } finally {
      setLoadingFeed(false);
    }
  }

  async function loadSubscription() {
    if (!token) return;
    try {
      setLoadingSub(true);
      const data = await apiFetch("/subscriptions/me", { token });
      setSubscription(data);
    } catch (e) {
      // Non-blocking for basic testing
      setSubscription(null);
    } finally {
      setLoadingSub(false);
    }
  }

  async function loadMatches() {
    if (!token) return;
    try {
      setLoadingMatches(true);
      const data = await apiFetch("/matches?limit=50&offset=0", { token });
      setMatches(data || []);
    } catch (e) {
      setMatches([]);
    } finally {
      setLoadingMatches(false);
    }
  }

  function connectWebSocket(userId) {
    if (!WS_URL) {
      setWsStatus("error");
      setWsError(tx("mobile.ws.missingUrl"));
      return;
    }
    setWsError("");
    setWsStatus("connecting");
    try {
      const ws = new WebSocket(`${WS_URL}/${userId}`);
      ws.onopen = () => setWsStatus("connected");
      ws.onerror = () => {
        setWsStatus("error");
        setWsError(tx("mobile.ws.error"));
      };
      ws.onclose = () => setWsStatus("disconnected");
      // Close after a short time; this is a connectivity check, not full chat UI.
      setTimeout(() => {
        try { ws.close(); } catch {}
      }, 2500);
    } catch (e) {
      setWsStatus("error");
      setWsError(tx("mobile.ws.failedStart"));
    }
  }

  useEffect(() => {
    debugEnvLog();
    setConfigWarnings(validateEnv());
  }, []);

  useEffect(() => {
    loadFeed();
    loadSubscription();
    loadMatches();
  }, [token]);

  if (!token) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: theme.bg, padding: 16 }}>
        <View style={{ marginBottom: 14 }}>
          <Text style={{ color: theme.text, fontSize: 30, fontWeight: '800' }}>NEYRA</Text>
          <Text style={{ color: theme.muted, marginTop: 6 }}>{tx("brand.tagline")}</Text>
        </View>
        {configWarnings.length ? (
          <View style={{ backgroundColor: "rgba(255,138,91,0.12)", borderColor: "rgba(255,138,91,0.30)", borderWidth: 1, padding: 12, borderRadius: 14, marginBottom: 12 }}>
            <Text style={{ color: theme.text, fontWeight: "800", marginBottom: 6 }}>{tx("mobile.configWarning.title")}</Text>
            {configWarnings.map((w) => (
              <Text key={w} style={{ color: theme.muted, fontSize: 12 }}>{w}</Text>
            ))}
          </View>
        ) : null}
        <View style={{ gap: 12, backgroundColor: theme.panel, borderRadius: theme.radius, padding: 14, borderWidth: 1, borderColor: theme.stroke }}>
          <TextInput style={{ backgroundColor: 'rgba(17,21,29,0.75)', borderColor: theme.stroke, borderWidth: 1, color: theme.text, padding: 12, borderRadius: 14 }} value={email} onChangeText={setEmail} placeholder={tx("auth.email.placeholder")} placeholderTextColor={theme.muted} />
          <TextInput style={{ backgroundColor: 'rgba(17,21,29,0.75)', borderColor: theme.stroke, borderWidth: 1, color: theme.text, padding: 12, borderRadius: 14 }} value={password} onChangeText={setPassword} secureTextEntry placeholder={tx("auth.password.placeholder")} placeholderTextColor={theme.muted} />
          <Pressable onPress={login} style={{ backgroundColor: theme.primary, padding: 14, borderRadius: 14 }}>
            <Text style={{ color: 'white', textAlign: 'center', fontWeight: '800' }}>{tx("common.continue")}</Text>
          </Pressable>
          {error ? <Text style={{ color: "rgba(255,91,122,0.92)", fontSize: 12 }}>{error}</Text> : null}
          <Text style={{ color: theme.muted, fontSize: 12 }}>{tx("mobile.login.tip")}</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.bg, padding: 16 }}>
      <View style={{ flexDirection: 'row', gap: 8, marginBottom: 16 }}>
        <Pressable onPress={() => setScreen('discover')} style={{ backgroundColor: theme.panel, padding: 12, borderRadius: 14, borderWidth: 1, borderColor: theme.stroke }}><Text style={{ color: theme.text, fontWeight: '700' }}>{tx("nav.discover")}</Text></Pressable>
        <Pressable onPress={() => setScreen('matches')} style={{ backgroundColor: theme.panel, padding: 12, borderRadius: 14, borderWidth: 1, borderColor: theme.stroke }}><Text style={{ color: theme.text, fontWeight: '700' }}>{tx("nav.matches")}</Text></Pressable>
        <Pressable onPress={() => setScreen('chat')} style={{ backgroundColor: theme.panel, padding: 12, borderRadius: 14, borderWidth: 1, borderColor: theme.stroke }}><Text style={{ color: theme.text, fontWeight: '700' }}>{tx("nav.chat")}</Text></Pressable>
        <Pressable onPress={() => setScreen('premium')} style={{ backgroundColor: theme.panel, padding: 12, borderRadius: 14, borderWidth: 1, borderColor: theme.stroke }}><Text style={{ color: theme.text, fontWeight: '700' }}>{tx("nav.premium")}</Text></Pressable>
      </View>

      {screen === 'discover' ? (
        <ScrollView contentContainerStyle={{ gap: 12 }}>
          {loadingFeed ? (
            <View style={{ backgroundColor: theme.panel, borderRadius: theme.radius, padding: 16, borderWidth: 1, borderColor: theme.stroke }}>
              <Text style={{ color: theme.muted }}>{tx("common.loading")}</Text>
            </View>
          ) : null}
          {cards.map((card) => (
            <View key={card.user_id} style={{ backgroundColor: theme.panel, borderRadius: theme.radius, padding: 16, borderWidth: 1, borderColor: theme.stroke }}>
              {card.is_demo_profile ? (
                <View style={{ alignSelf: "flex-start", backgroundColor: "rgba(255,255,255,0.08)", borderColor: theme.stroke, borderWidth: 1, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5, marginBottom: 8 }}>
                  <Text style={{ color: theme.text, fontSize: 12, fontWeight: "800" }}>{card.demo_label || tx("demo.profile.label")}</Text>
                </View>
              ) : null}
              <Text style={{ color: theme.text, fontSize: 20, fontWeight: '800' }}>{card.display_name}, {card.age || '?'}</Text>
              <Text style={{ color: theme.muted }}>{card.city} · {card.compatibility_score}%</Text>
              <Text style={{ color: theme.text, marginTop: 10 }}>{card.bio}</Text>
              {card.is_demo_profile ? (
                <Text style={{ color: theme.muted, marginTop: 10, fontSize: 12 }}>
                  {card.demo_disclaimer || tx("demo.profile.disclaimer")}
                </Text>
              ) : null}
            </View>
          ))}
          {!loadingFeed && cards.length === 0 ? (
            <View style={{ backgroundColor: theme.panel, borderRadius: theme.radius, padding: 16, borderWidth: 1, borderColor: theme.stroke }}>
              <Text style={{ color: theme.text, fontWeight: "800" }}>{tx("discover.empty.title")}</Text>
              <Text style={{ color: theme.muted, marginTop: 6 }}>{tx("discover.empty.subtitle")}</Text>
            </View>
          ) : null}
        </ScrollView>
      ) : screen === "matches" ? (
        <ScrollView contentContainerStyle={{ gap: 12 }}>
          <View style={{ backgroundColor: theme.panel, borderRadius: theme.radius, padding: 16, borderWidth: 1, borderColor: theme.stroke }}>
            <Text style={{ color: theme.text, fontSize: 20, fontWeight: '800' }}>{tx("nav.matches")}</Text>
            <Text style={{ color: theme.muted, marginTop: 6 }}>{tx("matches.header.subtitle")}</Text>
          </View>
          {loadingMatches ? (
            <View style={{ backgroundColor: theme.panel, borderRadius: theme.radius, padding: 16, borderWidth: 1, borderColor: theme.stroke }}>
              <Text style={{ color: theme.muted }}>{tx("common.loading")}</Text>
            </View>
          ) : null}
          {matches.map((m) => (
            <View key={m.match_id} style={{ backgroundColor: theme.panel, borderRadius: theme.radius, padding: 16, borderWidth: 1, borderColor: theme.stroke }}>
              <Text style={{ color: theme.text, fontWeight: "800" }}>{m.partner_display_name}</Text>
              <Text style={{ color: theme.muted }}>{m.partner_city}</Text>
              <Text style={{ color: theme.muted, marginTop: 6 }}>{tx("matches.field.userId")} {m.partner_user_id}</Text>
            </View>
          ))}
          {!loadingMatches && matches.length === 0 ? (
            <View style={{ backgroundColor: theme.panel, borderRadius: theme.radius, padding: 16, borderWidth: 1, borderColor: theme.stroke }}>
              <Text style={{ color: theme.text, fontWeight: "800" }}>{tx("matches.empty.title")}</Text>
              <Text style={{ color: theme.muted, marginTop: 6 }}>{tx("matches.empty.subtitle")}</Text>
            </View>
          ) : null}
        </ScrollView>
      ) : screen === "chat" ? (
        <View style={{ backgroundColor: theme.panel, borderRadius: theme.radius, padding: 16, borderWidth: 1, borderColor: theme.stroke }}>
          <Text style={{ color: theme.muted, fontSize: 12, marginBottom: 10 }}>{tx("demo.chat.banner")}</Text>
          <Text style={{ color: theme.text, fontSize: 20, fontWeight: '800' }}>{tx("mobile.chat.title")}</Text>
          <Text style={{ color: theme.muted, marginTop: 6 }}>{tx("mobile.chat.bannerNote")}</Text>
          <Text style={{ color: theme.muted, marginTop: 10 }}>{tx("mobile.chat.apiLine")} {API_URL || tx("mobile.config.valueMissing")}</Text>
          <Text style={{ color: theme.muted, marginTop: 6 }}>{tx("mobile.chat.wsLine")} {WS_URL || tx("mobile.config.valueMissing")}</Text>
          <Pressable
            onPress={() => connectWebSocket(1)}
            style={{ backgroundColor: theme.primary, padding: 14, borderRadius: 14, marginTop: 12 }}
          >
            <Text style={{ color: 'white', textAlign: 'center', fontWeight: '800' }}>{tx("mobile.chat.testWs")}</Text>
          </Pressable>
          <Text style={{ color: theme.text, marginTop: 12, fontWeight: "800" }}>{tx("mobile.chat.status")} {wsStatusLabel(wsStatus)}</Text>
          {wsError ? <Text style={{ color: "rgba(255,138,91,0.92)", marginTop: 6 }}>{wsError}</Text> : null}
          <Text style={{ color: theme.muted, marginTop: 10, fontSize: 12 }}>
            {tx("mobile.chat.wsNote")}
          </Text>
        </View>
      ) : (
        <View style={{ backgroundColor: theme.panel, borderRadius: theme.radius, padding: 16, borderWidth: 1, borderColor: theme.stroke }}>
          <Text style={{ color: theme.text, fontSize: 20, fontWeight: '800' }}>{tx("nav.premium")}</Text>
          <Text style={{ color: theme.muted, marginTop: 8 }}>{tx("mobile.premium.subtitle")}</Text>
          {loadingSub ? <Text style={{ color: theme.muted, marginTop: 10 }}>{tx("common.loading")}</Text> : null}
          <Text style={{ color: theme.text, marginTop: 10 }}>{JSON.stringify(subscription)}</Text>
        </View>
      )}
    </SafeAreaView>
  );
}
