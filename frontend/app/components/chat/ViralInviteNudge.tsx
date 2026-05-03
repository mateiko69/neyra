"use client";

import { useEffect, useState } from "react";
import { apiFetch, getToken } from "../../../lib/api";
import { useT } from "../i18n/I18nProvider";
import { Button, Card } from "../ui";

const STORAGE_KEY = "neyra:viral_invite_after_reply";

type ViralContextShape = {
  social_proof?: unknown;
  visibility_loop?: unknown;
  profile_highlight?: unknown;
};

export type ViralInviteNudgeProps = {
  onInvite: () => void;
  onDismiss: () => void;
};

export function shouldShowViralInviteAfterReply(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return sessionStorage.getItem(STORAGE_KEY) !== "1";
  } catch {
    return true;
  }
}

export function markViralInviteAfterReplySeen(): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, "1");
  } catch {
    /* ignore */
  }
}

export function ViralInviteNudge({ onInvite, onDismiss }: ViralInviteNudgeProps) {
  const { t } = useT("ViralInviteNudge");
  const [ctx, setCtx] = useState<ViralContextShape | null | undefined>(undefined);

  useEffect(() => {
    if (!getToken()) {
      setCtx(null);
      return;
    }
    let cancelled = false;
    void apiFetch("/growth/viral-context", { metaReason: "viral-context:invite_nudge", skipThrottle: true })
      .then((r) => {
        if (cancelled) return;
        if (!r || typeof r !== "object") {
          setCtx(null);
          return;
        }
        setCtx(r as ViralContextShape);
      })
      .catch(() => {
        if (!cancelled) setCtx(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (ctx === undefined || ctx === null) return null;

  return (
    <Card className="surface" style={{ marginTop: 10, padding: 12, borderRadius: 14 }}>
      <div className="section-label">{t("viral.inviteNudge.title")}</div>
      <p className="caption muted" style={{ marginTop: 8, lineHeight: 1.5 }}>
        {t("viral.inviteNudge.body")}
      </p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
        <Button
          type="button"
          onClick={() => {
            markViralInviteAfterReplySeen();
            onInvite();
          }}
        >
          {t("viral.inviteNudge.cta")}
        </Button>
        <Button
          type="button"
          variant="ghost"
          onClick={() => {
            markViralInviteAfterReplySeen();
            onDismiss();
          }}
        >
          {t("common.close")}
        </Button>
      </div>
    </Card>
  );
}
