"use client";

import { useEffect, useMemo, useState } from "react";
import { copilotFallbackFromPack, getChatFallbackPack } from "../../../lib/ai/chatFallbackReplies";
import type { AiLanguageToneContext, AiOpenerItem, AiOpenerMatchContext } from "../../../lib/chat/api";
import { getAiOpeners } from "../../../lib/chat/api";
import { useT } from "../i18n/I18nProvider";
import { Button } from "../ui";

type VariantKey = "friendly" | "playful" | "deep";

type Variant = {
  key: VariantKey;
  label: string;
  text: string;
  isBest: boolean;
};

function keyForItemType(type: AiOpenerItem["type"]): VariantKey {
  if (type === "safe") return "friendly";
  if (type === "flirty") return "playful";
  return "deep";
}

export function ChatFirstMessageSuggestion(props: {
  partnerUserId: number;
  matchContext: AiOpenerMatchContext;
  aiCtx?: AiLanguageToneContext;
  disabled?: boolean;
  onInsert: (text: string, meta: { variant: VariantKey; wasRecommended: boolean }) => void;
  onOtherOptions?: () => void;
}) {
  const { t, locale } = useT("ChatFirstMessageSuggestion");
  const [loading, setLoading] = useState(true);
  const [variants, setVariants] = useState<Variant[]>([]);
  const [selected, setSelected] = useState(0);
  const [expanded, setExpanded] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void (async () => {
      const res = await getAiOpeners(props.partnerUserId, props.matchContext, { aiCtx: props.aiCtx });
      if (cancelled) return;
      const items = (res.items || []).slice(0, 3);
      const best = Math.max(0, Math.min(items.length - 1, res.bestIndex ?? 0));
      let mapped: Variant[] = items.map((it, idx) => {
        const k = keyForItemType(it.type);
        const label =
          k === "friendly" ? t("chat.firstMessage.variant.friendly") : k === "playful" ? t("chat.firstMessage.variant.playful") : t("chat.firstMessage.variant.deep");
        return { key: k, label, text: String(it.text || "").trim(), isBest: idx === best };
      });
      mapped = mapped.filter((v) => Boolean(v.text));
      if (mapped.length === 0) {
        const pack = getChatFallbackPack(locale);
        const fb = copilotFallbackFromPack(pack);
        mapped = fb.map((row, idx) => ({
          key: idx === 0 ? "friendly" : idx === 1 ? "playful" : "deep",
          label: row.label,
          text: row.text,
          isBest: idx === 1,
        }));
      }
      setVariants(mapped);
      const bestPick = mapped.findIndex((v) => v.isBest);
      setSelected(bestPick >= 0 ? bestPick : Math.min(1, Math.max(0, mapped.length - 1)));
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.partnerUserId]);

  const active = variants[selected] ?? null;
  const bestIndex = useMemo(() => variants.findIndex((v) => v.isBest), [variants]);

  if (loading) {
    return (
      <div className="chat-first-opener chat-first-opener--in" aria-busy>
        <div className="chat-first-opener__badge">{t("chat.firstMessage.waiting")}</div>
        <div className="chat-first-opener__skeleton" />
        <div className="chat-first-opener__actions">
          <Button type="button" variant="primary" disabled className="chat-first-opener__send chat-first-opener__sendPulse">
            {t("chat.firstMessage.send")}
          </Button>
        </div>
      </div>
    );
  }

  if (!active) return null;

  return (
    <div className="chat-first-opener chat-first-opener--in" aria-label={t("chat.firstMessage.aria")}>
      <div className="chat-first-opener__badge">{t("chat.firstMessage.waiting")}</div>

      {expanded ? (
        <div className="chat-first-opener__options" role="list">
          {variants.map((v, idx) => (
            <button
              key={v.key}
              type="button"
              className={["chat-first-opener__option", idx === selected ? "chat-first-opener__option--selected" : ""].filter(Boolean).join(" ")}
              onClick={() => {
                setSelected(idx);
                props.onInsert(v.text, { variant: v.key, wasRecommended: idx === bestIndex });
              }}
              disabled={props.disabled}
            >
              <div className="chat-first-opener__option-type">
                {v.label} {v.isBest ? `· ${t("chat.firstMessage.best")}` : ""}
              </div>
              <div className="chat-first-opener__option-text">{v.text}</div>
            </button>
          ))}
        </div>
      ) : (
        <p className="chat-first-opener__text">{active.text}</p>
      )}

      <div className="chat-first-opener__actions" role="group" aria-label={t("chat.firstMessage.actionsAria")}>
        <Button type="button" variant="secondary" disabled={props.disabled} onClick={() => props.onOtherOptions?.()}>
          {t("chat.firstMessage.otherOptions")}
        </Button>
        <Button type="button" variant="ghost" disabled={props.disabled} onClick={() => setExpanded((v) => !v)}>
          {expanded ? t("chat.firstMessage.showOne") : t("chat.firstMessage.showAll")}
        </Button>
      </div>
    </div>
  );
}

