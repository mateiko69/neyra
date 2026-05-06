import { getBackendPublicOrigin } from "../apiBase";
import { apiFetch, getToken } from "../api";
import { debugChat } from "./debug";
import { CHAT_SYNC_EVENT, emitChatSync, type ChatSyncDetail } from "./api";

let ws: WebSocket | null = null;
let reconnectTimer: number | null = null;
let lastConnectAttemptAt = 0;
let connectedUserId: number | null = null;
let wsTokenPromise: Promise<string> | null = null;
let noTokenLogAt = 0;
let isConnecting = false;
let connectGen = 0;
let backoffMs = 1_000;
const BACKOFF_MAX_MS = 10_000;
const WS_MAX_RETRIES = 3;
let stopped = true;
let heartbeatTimer: number | null = null;
let wsDisabled = false;
let wsRetryCount = 0;

function clearHeartbeat() {
  if (heartbeatTimer != null) {
    window.clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}

function wsBaseUrl(): string {
  const origin = getBackendPublicOrigin();
  return origin.replace(/^http:/i, "ws:").replace(/^https:/i, "wss:");
}

function stopReconnect() {
  if (reconnectTimer != null) {
    window.clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
}

function emit(detail: ChatSyncDetail) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<ChatSyncDetail>(CHAT_SYNC_EVENT, { detail }));
}

async function getWsToken(): Promise<string> {
  if (!wsTokenPromise) {
    wsTokenPromise = apiFetch("/ws/token", { method: "POST", metaReason: "ws-token", softFail: true })
      .then((res: unknown) => String((res as { ws_token?: string } | undefined)?.ws_token || "").trim())
      .finally(() => {
        wsTokenPromise = null;
      });
  }
  const tok = await wsTokenPromise;
  return String(tok || "").trim();
}

function isUnauthorizedError(error: unknown): boolean {
  if (error && typeof error === "object" && "name" in error && (error as { name?: string }).name === "ApiUnauthorizedError") {
    return true;
  }
  return error instanceof Error && error.message.trim().toLowerCase() === "unauthorized";
}

function scheduleReconnect(uid: number, gen: number, minDelayMs: number = 1_000) {
  if (gen !== connectGen || stopped || wsDisabled) return;
  if (wsRetryCount >= WS_MAX_RETRIES) {
    wsDisabled = true;
    stopReconnect();
    console.warn("ws disabled after 401", { reason: "max_retries_reached", retries: wsRetryCount });
    return;
  }
  stopReconnect();
  const delay = Math.min(BACKOFF_MAX_MS, Math.max(minDelayMs, backoffMs));
  backoffMs = Math.min(BACKOFF_MAX_MS, Math.round(Math.max(1_000, backoffMs) * 2));
  wsRetryCount += 1;
  reconnectTimer = window.setTimeout(() => {
    const t = connectedUserId;
    if (t == null || t !== uid || gen !== connectGen || stopped || wsDisabled) return;
    void connectWS(t, gen);
  }, delay);
}

function safeSleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function connectWS(userId: number, gen: number) {
  if (typeof window === "undefined") return;
  if (isConnecting) return;
  isConnecting = true;

  try {
    if (gen !== connectGen) return;
    if (stopped) return;
    if (wsDisabled) return;

    const uid = Number(userId);
    if (!Number.isFinite(uid) || uid < 1) {
      return;
    }
    if (connectedUserId == null || connectedUserId !== uid) return;

    stopReconnect();
    clearHeartbeat();
    if (ws) {
      try {
        ws.onclose = null;
        ws.onerror = null;
        ws.onmessage = null;
        ws.onopen = null;
        ws.close();
      } catch {
        /* ignore */
      }
      ws = null;
    }

    const now = Date.now();
    if (now - lastConnectAttemptAt < 1_000) return;
    lastConnectAttemptAt = now;

    // Always fetch a fresh short-lived ws_token right before connect.
    let wsToken = "";
    try {
      wsToken = await getWsToken();
    } catch (e) {
      if (gen !== connectGen || stopped) return;
      if (isUnauthorizedError(e)) {
        wsDisabled = true;
        stopReconnect();
        console.warn("ws disabled after 401", { reason: "ws_token_unauthorized" });
        return;
      }
      scheduleReconnect(uid, gen, 1_000);
      return;
    }
    if (gen !== connectGen) return;
    if (stopped) return;
    if (connectedUserId !== uid) return;
    const safeToken = String(wsToken || "").trim();
    if (!safeToken) {
      if (typeof process !== "undefined" && process.env.NODE_ENV !== "production") {
        const tlog = Date.now();
        if (tlog - noTokenLogAt > 25_000) {
          noTokenLogAt = tlog;
          console.debug("[neyra-ws] ws_token empty (session/bootstrap race); retry scheduled");
        }
      }
      scheduleReconnect(uid, gen, 1_000);
      return;
    }

    const url = `${wsBaseUrl()}/api/v1/ws/chat/${uid}?ws_token=${encodeURIComponent(safeToken)}`;
    // Debug (no secrets): never log ws_token or full URL.
    if (typeof process !== "undefined" && process.env.NODE_ENV !== "production") {
      console.log("WS DEBUG", {
        userId: uid,
        tokenPreview: safeToken.slice(0, 10),
        isTokenPresent: Boolean(safeToken),
      });
      console.log("WS CONNECT", `/api/v1/ws/chat/${uid}?ws_token=…`);
    }
    debugChat("ws connect", { url: "/api/v1/ws/chat/{userId}", userId: uid });

    ws = new WebSocket(url);

    ws.onopen = () => {
      backoffMs = 1_000;
      wsRetryCount = 0;
      if (typeof process !== "undefined" && process.env.NODE_ENV !== "production") {
        console.log("WS CONNECTED");
      }
      debugChat("ws open", { userId: uid });
      emitChatSync({ type: "wsReconnected" });
      clearHeartbeat();
      heartbeatTimer = window.setInterval(() => {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        try {
          ws.send(JSON.stringify({ type: "ping" }));
        } catch {
          /* ignore */
        }
      }, 20_000);
    };

    ws.onmessage = (event) => {
      let data: any = null;
      try {
        data = JSON.parse(String(event.data || ""));
      } catch {
        return;
      }
      if (!data || typeof data !== "object") return;
      if (data.type !== "message") return;

      const senderId = Number(data.sender_id);
      const receiverId = Number(data.receiver_id);
      if (!Number.isFinite(senderId) || !Number.isFinite(receiverId)) return;

      // Incoming message for the currently signed-in user (prefer live id if session rotated).
      const me = connectedUserId ?? uid;
      if (receiverId === me && senderId > 0) {
        emit({ type: "messageReceived", partnerUserId: Math.trunc(senderId) });
      }
    };

    ws.onclose = async (e) => {
      clearHeartbeat();
      ws = null;
      if (gen !== connectGen) return;
      if (stopped) return;
      stopReconnect();
      const closeCode = Number((e as any)?.code ?? 0);

      // 4401 = backend rejected token (missing/expired/invalid). Refetch quickly with fresh token.
      if (closeCode === 4401) {
        if (wsRetryCount >= WS_MAX_RETRIES) {
          wsDisabled = true;
          stopReconnect();
          console.warn("ws disabled after 401", { reason: "close_4401", retries: wsRetryCount });
          return;
        }
        backoffMs = Math.max(500, backoffMs);
      }

      const delay = Math.min(BACKOFF_MAX_MS, Math.max(500, backoffMs));
      backoffMs = Math.min(BACKOFF_MAX_MS, Math.round(Math.max(1_000, backoffMs) * 2));
      wsRetryCount += 1;
      if (typeof process !== "undefined" && process.env.NODE_ENV !== "production") {
        console.warn("WS CLOSED", closeCode || undefined, "→ reconnecting…", { delayMs: delay });
      }
      await safeSleep(delay);
      if (gen !== connectGen || stopped) return;
      const target = connectedUserId;
      if (target == null || target !== uid) return;
      void connectWS(target, gen);
    };

    ws.onerror = () => {
      // Ensure close triggers reconnect path.
      try {
        ws?.close();
      } catch {
        /* ignore */
      }
    };
  } finally {
    isConnecting = false;
  }
}

export function startChatRealtime(userId: number) {
  if (typeof window === "undefined") return;
  const uid = Number(userId);
  if (!Number.isFinite(uid) || uid < 1) return;
  if (!getToken()?.trim()) {
    if (typeof process !== "undefined" && process.env.NODE_ENV !== "production") {
      const tlog = Date.now();
      if (tlog - noTokenLogAt > 25_000) {
        noTokenLogAt = tlog;
        console.debug("[neyra-ws] skip realtime start until auth token is available");
      }
    }
    return;
  }
  if (connectedUserId === uid && ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  // IMPORTANT: stop first; stopChatRealtime clears connectedUserId.
  stopChatRealtime();
  connectedUserId = uid;
  stopped = false;
  connectGen += 1;
  backoffMs = 1_000;
  wsDisabled = false;
  wsRetryCount = 0;
  void connectWS(uid, connectGen);
}

export function stopChatRealtime() {
  if (typeof window === "undefined") return;
  wsTokenPromise = null;
  clearHeartbeat();
  stopReconnect();
  stopped = true;
  connectGen += 1;
  isConnecting = false;
  backoffMs = 1_000;
  wsDisabled = false;
  wsRetryCount = 0;
  if (ws) {
    try {
      ws.onclose = null;
      ws.onerror = null;
      ws.onmessage = null;
      ws.onopen = null;
      ws.close();
    } catch {
      /* ignore */
    }
  }
  ws = null;
  connectedUserId = null;
}

