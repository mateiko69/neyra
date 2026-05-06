"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchDiscoverOpenerSuggestions } from "../../../lib/discover/openersApi";
import type { DiscoverCardData } from "./DiscoverProfileCard";
import { useT } from "../../components/i18n/I18nProvider";
import { Button } from "../../components/ui";
import { ApiPaywallError } from "../../../lib/api";
type Props = {
  card: DiscoverCardData;
};

export function DiscoverInlineOpeners({ card }: Props) {
  const { t, locale } = useT("DiscoverInlineOpeners");
  const [panelOpen, setPanelOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [paywallHint, setPaywallHint] = useState(false);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [edited, setEdited] = useState<Record<number, string>>({});
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);

  useEffect(() => {
    setPaywallHint(false);
    setPanelOpen(false);
    setLines([]);
    setError(null);
    setEdited({});
    setEditingIdx(null);
    setEditDraft("");
    setRefreshNonce(0);
    setCopiedIdx(null);
  }, [card.user_id]);

  const matchName = (String(card.display_name || "").trim() || t("discover.card.aiNameFallback")).slice(0, 80);
  const tags = (Array.isArray(card.top_reasons) ? card.top_reasons : []).map((x) => String(x || "").trim()).filter(Boolean).slice(0, 8);

  const lineText = useCallback(
    (i: number) => {
      const e = edited[i];
      if (e != null && String(e).trim()) return String(e).trim();
      return String(lines[i] || "").trim();
    },
    [edited, lines],
  );

  const load = useCallback(
    async (nonce: number) => {
      setLoading(true);
      setError(null);
      try {
        const r = await fetchDiscoverOpenerSuggestions({
          matchName,
          bio: card.bio,
          interests: (card.interests || []).map((x) => String(x)),
          city: card.city,
          tags,
          locale: locale || "en",
          refreshNonce: nonce,
        });
        const next = (r.suggestions.length ? r.suggestions : r.items.map((x) => x.text)).filter(Boolean).slice(0, 3);
        setLines(next);
        setEdited({});
        setEditingIdx(null);
        setEditDraft("");
      } catch (e: unknown) {
        if (e instanceof ApiPaywallError) {
          setPaywallHint(true);
          setLines([]);
          setError(null);
          return;
        }
        setLines([]);
        setError(e instanceof Error && e.message.trim() ? e.message.trim() : t("discover.openers.error"));
      } finally {
        setLoading(false);
      }
    },
    [card.bio, card.city, card.interests, locale, matchName, tags, t],
  );

  const onNext = useCallback(() => {
    const next = refreshNonce + 1;
    setRefreshNonce(next);
    void load(next);
  }, [load, refreshNonce]);

  const toggleEdit = useCallback(
    (i: number) => {
      if (editingIdx === i) {
        setEdited((m) => ({ ...m, [i]: editDraft.trim() || lineText(i) }));
        setEditingIdx(null);
        return;
      }
      setEditingIdx(i);
      setEditDraft(lineText(i));
    },
    [editDraft, editingIdx, lineText],
  );

  const onSend = useCallback(
    async (i: number) => {
      const text = editingIdx === i ? editDraft.trim() : lineText(i);
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
        setCopiedIdx(i);
        window.setTimeout(() => setCopiedIdx((x) => (x === i ? null : x)), 2000);
      } catch {
        setError(t("discover.openers.copyFailed"));
        window.setTimeout(() => setError(null), 3000);
      }
    },
    [editDraft, editingIdx, lineText, t],
  );

  return (
    <div className="discover-inline-openers">
      {paywallHint ? (
        <div className="caption" style={{ marginBottom: 10, padding: "10px 12px", borderRadius: 12, border: "1px solid rgba(124,92,255,0.28)", background: "rgba(124,92,255,0.08)" }}>
          {t("monetization.discover.softHint")}
        </div>
      ) : null}
      <button
        type="button"
        className="btn btn-secondary discover-inline-openers__cta"
        aria-expanded={panelOpen}
        aria-controls={`discover-openers-${card.user_id}`}
        onClick={() => {
          if (panelOpen) {
            setPanelOpen(false);
            return;
          }
          setPanelOpen(true);
          if (lines.length >= 3 && !error) return;
          void load(refreshNonce);
        }}
      >
        ✨ {t("discover.ai.whatShouldISay")}
      </button>

      {panelOpen ? (
        <div
          id={`discover-openers-${card.user_id}`}
          className="discover-inline-openers__panel surface"
          role="region"
          aria-label={t("discover.openers.regionAria")}
        >
          {loading ? (
            <div className="caption discover-inline-openers__loading">{t("discover.openers.loading")}</div>
          ) : error ? (
            <div className="caption discover-inline-openers__error">{error}</div>
          ) : (
            <>
              <ul className="discover-inline-openers__list">
                {lines.map((_, i) => {
                  const showEdit = editingIdx === i;
                  return (
                    <li key={`${card.user_id}-op-${i}`} className="discover-inline-openers__item">
                      {showEdit ? (
                        <textarea
                          className="discover-inline-openers__textarea"
                          value={editDraft}
                          onChange={(e) => setEditDraft(e.target.value)}
                          rows={2}
                          aria-label={t("discover.openers.editAria", { n: i + 1 })}
                        />
                      ) : (
                        <p className="discover-inline-openers__line">{lineText(i)}</p>
                      )}
                      <div className="discover-inline-openers__row-actions">
                        <button
                          type="button"
                          className="btn btn-ghost discover-inline-openers__mini"
                          title={t("discover.openers.sendHint")}
                          onClick={() => void onSend(i)}
                        >
                          {copiedIdx === i ? t("discover.openers.copied") : t("discover.openers.send")}
                        </button>
                        <button type="button" className="btn btn-ghost discover-inline-openers__mini" onClick={() => toggleEdit(i)}>
                          {showEdit ? t("discover.openers.done") : t("discover.openers.edit")}
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
              <div className="discover-inline-openers__footer">
                <Button type="button" variant="secondary" disabled={loading} onClick={() => void onNext()}>
                  {t("discover.openers.next")}
                </Button>
                <Button type="button" variant="ghost" disabled={loading} onClick={() => setPanelOpen(false)}>
                  {t("common.close")}
                </Button>
              </div>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
