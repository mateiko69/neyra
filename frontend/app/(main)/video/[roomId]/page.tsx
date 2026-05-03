"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import DailyIframe from "@daily-co/daily-js";
import { useT } from "../../../components/i18n/I18nProvider";

function dailyRoomUrlFromRoomId(roomId: string): string {
  const domain = String(process.env.NEXT_PUBLIC_DAILY_DOMAIN || "").trim().replace(/^https?:\/\//, "").replace(/\/+$/, "");
  if (!domain) return "";
  return `https://${domain}/${roomId}`;
}

export default function VideoRoomPage() {
  const { t } = useT("VideoRoomPage");
  const params = useParams() as { roomId?: string };
  const search = useSearchParams();
  const router = useRouter();

  const roomId = String(params?.roomId || "").trim();
  const roomUrl = useMemo(() => {
    const q = String(search?.get("url") || "").trim();
    if (q.startsWith("https://")) return q;
    if (!roomId) return "";
    return dailyRoomUrlFromRoomId(roomId);
  }, [roomId, search]);

  const frameHostRef = useRef<HTMLDivElement | null>(null);
  const callRef = useRef<any>(null);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    if (!roomId) return;
    if (!roomUrl) {
      setError(t("video.missingDailyConfig"));
      return;
    }
    const host = frameHostRef.current;
    if (!host) return;
    if (callRef.current) return;

    const call = DailyIframe.createFrame(host, {
      showLeaveButton: true,
    });
    callRef.current = call;

    void (async () => {
      try {
        await call.join({ url: roomUrl });
      } catch {
        setError(t("video.joinFailed"));
      }
    })();

    return () => {
      try {
        call?.destroy();
      } catch {
        /* ignore */
      }
      callRef.current = null;
    };
  }, [roomId, roomUrl, t]);

  return (
    <div style={{ padding: 18 }}>
      <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12 }}>
        <button type="button" className="btn btn-ghost" onClick={() => router.push("/chat")}>
          {t("video.backToChats")}
        </button>
        <div style={{ fontWeight: 900 }}>{t("video.title")}</div>
      </div>
      {error ? (
        <div className="surface" style={{ padding: 14, borderRadius: 16, border: "1px solid rgba(255,255,255,0.10)" }}>
          <div style={{ fontWeight: 900, marginBottom: 6 }}>{t("video.errorTitle")}</div>
          <div className="caption" style={{ opacity: 0.85 }}>
            {error}
          </div>
        </div>
      ) : null}
      <div ref={frameHostRef} style={{ width: "100%", height: "72vh", borderRadius: 18, overflow: "hidden", marginTop: 12 }} />
    </div>
  );
}

