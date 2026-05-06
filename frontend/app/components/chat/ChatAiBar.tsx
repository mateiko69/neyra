"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { ChatMessage } from "../../../lib/chat/types";
import { conversationContext } from "../../../lib/chat/normalize";
import {
  getAiRewriteVariants,
  postChatBrainSuggestions,
  type AiLanguageToneContext,
  type ChatBrainRequestMode,
  type ChatBrainVariantKey,
} from "../../../lib/chat/api";
import type { AiTier } from "../../../lib/chat/aiTier";
import { aiChatContextMessageLimit } from "../../../lib/chat/aiTier";
import { useT } from "../i18n/I18nProvider";
import { Button } from "../ui";
import { neyraChatSuggestionDevLog } from "../../../lib/chat/neyraAiLocaleLog";

type Props = {
  partnerUserId: number | null;
  viewerUserId: number | null;
  messages: ChatMessage[];
  draft: string;
  disabled?: boolean;
  aiCtx?: AiLanguageToneContext;
  /** Drives rewrite context depth (5 vs 50) and premium-only rewrite modes. */
  aiTier?: AiTier;
  onInsertDraft: (text: string) => void;
};

type VariantPack = Record<ChatBrainVariantKey, string>;

const GENERIC_HELLO = /^(hey+|hi+|hello+)(\s*[!.❤️♥☺:\)]+)?(\s+how\s+are\s+you\??)?\s*$/i;

function isTooGeneric(text: string): boolean {
  const s = String(text || "").trim();
  if (!s) return true;
  return GENERIC_HELLO.test(s);
}

function parseMessageMs(m: ChatMessage): number | null {
  const tsRaw = String((m as any)?.timestamp ?? (m as any)?.createdAt ?? "").trim();
  if (!tsRaw) return null;
  const ms = Date.parse(tsRaw);
  return Number.isFinite(ms) ? ms : null;
}

function variantLabel(t: (k: string, vars?: any) => string, key: ChatBrainVariantKey): string {
  if (key === "flirty") return t("chat.aiBar.variant.flirty");
  if (key === "deep") return t("chat.aiBar.variant.deep");
  return t("chat.aiBar.variant.playful");
}

function modeForThread(input: {
  partnerUserId: number | null;
  viewerUserId: number | null;
  messages: ChatMessage[];
  wantsNudge: boolean;
}): ChatBrainRequestMode {
  const { partnerUserId, viewerUserId, messages, wantsNudge } = input;
  if (!partnerUserId || !viewerUserId) return "auto";
  if (!messages.length) return "opener";
  if (wantsNudge) return "revive";
  const last = messages[messages.length - 1] ?? null;
  if (!last) return "auto";
  if (Number(last.senderId) === Number(partnerUserId)) return "reply";
  return "auto";
}

export function ChatAiBar({
  partnerUserId,
  viewerUserId,
  messages,
  draft,
  disabled = false,
  aiCtx,
  aiTier = "free",
  onInsertDraft,
}: Props) {
  const { t, locale: uiLocaleTag } = useT("ChatAiBar");
  const [isMobile, setIsMobile] = useState(false);
  const draftTrim = String(draft || "").trim();

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(max-width: 1023px)");
    const apply = () => setIsMobile(Boolean(mq.matches));
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  const lastIncoming = useMemo(() => {
    if (!partnerUserId) return null;
    const last = (messages || []).slice(-1)[0] ?? null;
    if (!last) return null;
    if (Number(last.senderId) !== Number(partnerUserId)) return null;
    const text = String((last as any).content || "").trim();
    if (!text) return null;
    return last;
  }, [messages, partnerUserId]);

  const wantsNudge = useMemo(() => {
    if (!partnerUserId || !viewerUserId) return false;
    if (!messages.length) return false;
    const last = messages[messages.length - 1] ?? null;
    if (!last) return false;
    if (Number(last.senderId) !== Number(partnerUserId)) return false;
    const ms = parseMessageMs(last);
    if (!ms) return false;
    const ageMs = Date.now() - ms;
    return ageMs >= 12 * 60 * 60 * 1000;
  }, [messages, partnerUserId, viewerUserId]);

  const mode = useMemo(
    () =>
      modeForThread({
        partnerUserId,
        viewerUserId,
        messages,
        wantsNudge,
      }),
    [messages, partnerUserId, viewerUserId, wantsNudge],
  );

  const lastIncomingKey = useMemo(() => {
    if (!lastIncoming) return "";
    return String((lastIncoming as any).rawId ?? (lastIncoming as any).id ?? (lastIncoming as any).createdAt ?? "");
  }, [lastIncoming]);

  const [pack, setPack] = useState<VariantPack>({ light: "", flirty: "", deep: "" });
  const [loading, setLoading] = useState(false);
  const [typing, setTyping] = useState(false);
  const [open, setOpen] = useState(false);
  const [rewriteOpen, setRewriteOpen] = useState(false);
  const [rewriteLoading, setRewriteLoading] = useState(false);
  const [rewriteVariants, setRewriteVariants] = useState<{ label: string; text: string }[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const typingTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (typingTimerRef.current != null) window.clearTimeout(typingTimerRef.current);
    };
  }, []);

  useEffect(() => {
    setRewriteOpen(false);
    setRewriteVariants([]);
    setRewriteLoading(false);
  }, [partnerUserId, uiLocaleTag]);

  async function fetchSuggestions() {
    if (!partnerUserId || !viewerUserId) return;
    if (disabled) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setTyping(true);
    setOpen(true);
    try {
      const res = await postChatBrainSuggestions({
        partnerUserId,
        // Explicit user action: let server decide best mode, but always return 3 variants.
        mode: "auto",
        tone: "auto",
        language: uiLocaleTag,
        aiCtx: { ...(aiCtx ?? {}), uiLocale: uiLocaleTag },
        signal: controller.signal,
      });
      if (!res?.ok) return;
      const nextPack = {
        light: String(res.variants.light || "").trim(),
        flirty: String(res.variants.flirty || "").trim(),
        deep: String(res.variants.deep || "").trim(),
      };
      // Block generic lines (final safety).
      for (const k of ["light", "flirty", "deep"] as ChatBrainVariantKey[]) {
        if (isTooGeneric(nextPack[k])) (nextPack as any)[k] = "";
      }
      // Typing simulation: delay visible suggestions slightly (no instant AI).
      if (typingTimerRef.current != null) window.clearTimeout(typingTimerRef.current);
      const delayMs = 2000 + Math.trunc(Math.random() * 2000);
      typingTimerRef.current = window.setTimeout(() => {
        typingTimerRef.current = null;
        setPack(nextPack);
        setTyping(false);

        const fromPartner = (messages || [])
          .slice()
          .reverse()
          .find((m) => Number((m as any).senderId) === Number(partnerUserId));
        const lastPrev = String((fromPartner as any)?.content ?? "").trim().slice(0, 220);
        neyraChatSuggestionDevLog({
          component: "ChatAiBar",
          endpoint: "/api/v1/ai/chat-brain/suggestions",
          locale: uiLocaleTag,
          source: Boolean(res.meta?.ai_used) ? "ai" : "fallback",
          fallback: Boolean(!res.meta?.ai_used),
          last_message_preview: lastPrev,
        });
      }, delayMs);
    } catch {
      // Silent-fail.
    } finally {
      setLoading(false);
    }
  }

  const canRewrite = draftTrim.length > 0 && !disabled;

  async function runRewrite() {
    if (!partnerUserId || !viewerUserId) return;
    if (!canRewrite) return;
    setRewriteOpen(true);
    setRewriteLoading(true);
    setRewriteVariants([]);
    try {
      const ctxLim = aiChatContextMessageLimit(aiTier);
      const ctx = conversationContext(messages, ctxLim);
      const isPaidTier = aiTier === "premium" || aiTier === "premium_plus";
      const [shorter, playful, confident] = await Promise.all([
        getAiRewriteVariants(partnerUserId, draftTrim, { conversationContext: ctx, mode: "shorter", aiCtx: { ...(aiCtx ?? {}), uiLocale: uiLocaleTag } }),
        getAiRewriteVariants(partnerUserId, draftTrim, {
          conversationContext: ctx,
          mode: isPaidTier ? "witty" : "natural",
          aiCtx: { ...(aiCtx ?? {}), uiLocale: uiLocaleTag },
        }),
        getAiRewriteVariants(partnerUserId, draftTrim, {
          conversationContext: ctx,
          mode: isPaidTier ? "confident" : "polish",
          aiCtx: { ...(aiCtx ?? {}), uiLocale: uiLocaleTag },
        }),
      ]);
      const pick = (arr: string[]) => (arr || []).map((x) => String(x || "").trim()).filter((s) => s && !isTooGeneric(s))[0] || "";
      setRewriteVariants([
        { label: t("chat.aiBar.rewrite.shorter"), text: pick(shorter) },
        { label: t("chat.aiBar.rewrite.playful"), text: pick(playful) },
        { label: t("chat.aiBar.rewrite.confident"), text: pick(confident) },
      ]);
    } finally {
      setRewriteLoading(false);
    }
  }

  const items = useMemo(() => {
    const v: { key: ChatBrainVariantKey; label: string; text: string }[] = [
      { key: "light", label: variantLabel(t, "light"), text: String(pack.light || "").trim() },
      { key: "flirty", label: variantLabel(t, "flirty"), text: String(pack.flirty || "").trim() },
      { key: "deep", label: variantLabel(t, "deep"), text: String(pack.deep || "").trim() },
    ];
    return v;
  }, [pack.deep, pack.flirty, pack.light, t]);

  const compactItems = useMemo(
    () => items.slice(0, 3).filter((it) => String(it.text || "").trim() && !isTooGeneric(it.text)),
    [items],
  );

  if (isMobile) {
    return (
      <div
        data-testid="ai-suggestions"
        className="chat-ai-bar chat-ai-bar--compact"
        aria-label={t("chat.aiBar.aria")}
        style={{
          padding: "8px 10px",
          borderRadius: 12,
          border: "1px solid rgba(255,255,255,0.10)",
          background: "rgba(255,255,255,0.05)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
          <div style={{ fontWeight: 820 }}>{t("chat.aiBar.title")}</div>
          <Button
            type="button"
            variant="secondary"
            disabled={disabled || loading}
            onClick={() => void fetchSuggestions()}
          >
            {t("chat.aiBar.ask")}
          </Button>
        </div>
        {compactItems.length ? (
          <div className="chat-ai__suggestions" style={{ marginTop: 8 }}>
            {compactItems.map((it) => (
              <button
                key={`compact-${it.key}`}
                type="button"
                className="chat-ai__suggestion"
                disabled={disabled}
                onClick={() => onInsertDraft(String(it.text || "").trim())}
              >
                <div className="caption" style={{ opacity: 0.8 }}>
                  {it.label}
                </div>
                <div className="chat-ai__suggestion-text chat-ai__suggestion-text--compact">{it.text}</div>
              </button>
            ))}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div
      data-testid="ai-suggestions"
      className="chat-ai-bar"
      aria-label={t("chat.aiBar.aria")}
      style={{
        padding: "10px 10px 8px",
        borderRadius: 14,
        border: "1px solid rgba(255,255,255,0.10)",
        background: "rgba(255,255,255,0.05)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center" }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", minWidth: 0 }}>
          <div style={{ fontWeight: 850, letterSpacing: "-0.02em" }}>✨ {t("chat.aiBar.title")}</div>
          {typing || loading ? (
            <div className="caption" style={{ opacity: 0.75 }}>
              {t("chat.aiBar.loading")}
            </div>
          ) : null}
          {wantsNudge && draftTrim.length === 0 ? (
            <div className="caption" style={{ opacity: 0.85 }}>
              {t("chat.aiBar.nudgeHint")}
            </div>
          ) : null}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Button type="button" variant="secondary" disabled={disabled || loading} onClick={() => void fetchSuggestions()}>
            {t("chat.aiBar.ask")}
          </Button>
          {canRewrite ? (
            <Button type="button" variant="secondary" disabled={rewriteLoading} onClick={() => void runRewrite()}>
              {t("chat.aiBar.rewrite")}
            </Button>
          ) : null}
        </div>
      </div>

      {rewriteOpen ? (
        <div style={{ marginTop: 10 }}>
          <div className="caption" style={{ opacity: 0.85, fontWeight: 750 }}>
            {t("chat.aiBar.improvedTitle")}
          </div>
          {rewriteLoading ? (
            <div className="caption" style={{ marginTop: 6, opacity: 0.75 }}>
              {t("chat.aiBar.loading")}
            </div>
          ) : null}
          <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
            {(rewriteVariants.length ? rewriteVariants : [{ label: "", text: "" }, { label: "", text: "" }, { label: "", text: "" }])
              .slice(0, 3)
              .map((row, idx) => (
              <button
                key={`rewrite-${idx}`}
                type="button"
                disabled={disabled || rewriteLoading || !String(row?.text || "").trim()}
                onClick={() => {
                  const v = String(row?.text || "").trim();
                  if (!v) return;
                  onInsertDraft(v);
                }}
                style={{
                  width: "100%",
                  textAlign: "left",
                  borderRadius: 14,
                  border: "1px solid rgba(255,255,255,0.10)",
                  background: "rgba(0,0,0,0.20)",
                  padding: "10px 12px",
                  cursor: disabled ? "not-allowed" : "pointer",
                  opacity: disabled ? 0.7 : 1,
                }}
              >
                <div className="caption" style={{ opacity: 0.78 }}>{row?.label || t("chat.aiBar.variant.improvedOption", { index: idx + 1 })}</div>
                <div className="text-white/90" style={{ marginTop: 4, lineHeight: 1.35, fontWeight: 650 }}>
                  {String(row?.text || "…")}
                </div>
              </button>
            ))}
          </div>
          <div style={{ marginTop: 10, display: "flex", justifyContent: "flex-end" }}>
            <Button type="button" variant="ghost" onClick={() => setRewriteOpen(false)}>
              {t("common.close")}
            </Button>
          </div>
        </div>
      ) : (
        <div style={{ marginTop: 10, display: "grid", gap: 8 }}>
          {open && draftTrim.length === 0 ? items.map((it) => (
            <button
              key={it.key}
              type="button"
              disabled={disabled || draftTrim.length > 0 || !String(it.text || "").trim() || isTooGeneric(it.text)}
              onClick={() => {
                const text = String(it.text || "").trim();
                if (!text) return;
                onInsertDraft(text);
              }}
              style={{
                width: "100%",
                textAlign: "left",
                borderRadius: 14,
                border: "1px solid rgba(255,255,255,0.10)",
                background: "rgba(0,0,0,0.20)",
                padding: "10px 12px",
                cursor: disabled ? "not-allowed" : "pointer",
                opacity: disabled ? 0.7 : 1,
              }}
            >
              <div className="caption" style={{ opacity: 0.78 }}>
                {it.label}
              </div>
              <div className="text-white/90" style={{ marginTop: 4, lineHeight: 1.35, fontWeight: 650 }}>
                {it.text || "…"}
              </div>
            </button>
          )) : (
            <div className="caption" style={{ opacity: 0.8 }}>
              {t("chat.aiBar.ask")}
            </div>
          )}
          {draftTrim.length > 0 ? (
            <div className="caption" style={{ opacity: 0.8 }}>
              {t("chat.aiBar.typeHint")}
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

