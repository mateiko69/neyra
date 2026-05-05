"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { apiFetch, apiUpload, formatApiError } from "../../../lib/api";
import { resolveI18nText } from "../../../lib/i18n/message";
import { apiFailureToI18nText } from "../../../lib/i18n/translateApiUserMessage";
import { useT } from "../i18n/I18nProvider";
import { Button } from "../ui";

type VerifyStartResponse = { pose_challenge?: string; session_id?: string };

type SubmitResponse = { status?: string; verification_status?: string; ok?: boolean };

type Props = {
  open: boolean;
  onClose: () => void;
  onComplete: () => void;
};

async function captureOneFrame(video: HTMLVideoElement): Promise<Blob> {
  const w = video.videoWidth;
  const h = video.videoHeight;
  if (w < 2 || h < 2) throw new Error("video-not-ready");
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("no-ctx");
  ctx.drawImage(video, 0, 0, w, h);
  return await new Promise<Blob>((res, rej) => {
    canvas.toBlob((b) => (b ? res(b) : rej(new Error("blob"))), "image/jpeg", 0.88);
  });
}

export function VerificationFlowModal({ open, onClose, onComplete }: Props) {
  const { t } = useT("VerificationFlowModal");
  const [cameraError, setCameraError] = useState("");
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [phase, setPhase] = useState<"flow" | "uploading" | "success" | "pending" | "rejected">("flow");
  const [streamReady, setStreamReady] = useState(false);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const stopStream = useCallback(() => {
    const s = streamRef.current;
    streamRef.current = null;
    setStreamReady(false);
    if (s) {
      for (const tr of s.getTracks()) {
        try {
          tr.stop();
        } catch {
          /* ignore */
        }
      }
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  }, []);

  useEffect(() => {
    if (!open) {
      stopStream();
      setSubmitError("");
      setPhase("flow");
      setBusy(false);
      setCameraError("");
      setStreamReady(false);
      return;
    }
    void apiFetch("/verify/start", {
      method: "POST",
      body: JSON.stringify({}),
      metaReason: "verify-start",
      skipThrottle: true,
      skipCache: true,
    }).catch(() => {});
    return () => stopStream();
  }, [open, stopStream]);

  const startCamera = useCallback(async () => {
    setCameraError("");
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraError(t("profile.verify.errors.browserNoCamera"));
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 720 } },
        audio: false,
      });
      stopStream();
      streamRef.current = stream;
      const v = videoRef.current;
      if (v) {
        v.srcObject = stream;
        await v.play();
      }
      setStreamReady(true);
    } catch {
      setCameraError(t("profile.verify.errors.cameraDenied"));
      setStreamReady(false);
    }
  }, [stopStream, t]);

  const submitBlob = useCallback(
    async (blob: Blob, source: "camera" | "upload") => {
      setBusy(true);
      setSubmitError("");
      setPhase("uploading");
      const signal =
        typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function"
          ? AbortSignal.timeout(60_000)
          : undefined;
      try {
        const fd = new FormData();
        fd.append("verification_source", source);
        fd.append("pose_challenge", "");
        fd.append("captured_at", new Date().toISOString());
        fd.append("frames", blob, "selfie.jpg");
        const raw = await apiUpload("/verify/submit", fd, { metaReason: "verify-submit", signal });
        const res = raw as SubmitResponse;
        const st = String(res.status || res.verification_status || "").toLowerCase();
        if (st === "approved" || st === "verified") {
          setPhase("success");
          stopStream();
          window.setTimeout(() => {
            onComplete();
            onClose();
          }, 2200);
          return;
        }
        if (st === "pending" || st === "pending_manual_review") {
          setPhase("pending");
          stopStream();
          onComplete();
          return;
        }
        setPhase("rejected");
        setSubmitError(t("verification.flow.rejectedHint"));
      } catch (e: unknown) {
        setPhase("flow");
        setSubmitError(resolveI18nText(apiFailureToI18nText(e, t, "profile.verify.errors.tryAgainGeneric", formatApiError), t));
      } finally {
        setBusy(false);
      }
    },
    [onClose, onComplete, stopStream, t],
  );

  const onCaptureCamera = useCallback(async () => {
    const v = videoRef.current;
    if (!v) return;
    try {
      const blob = await captureOneFrame(v);
      await submitBlob(blob, "camera");
    } catch {
      setSubmitError(t("profile.verify.errors.notEnoughFrames"));
    }
  }, [submitBlob, t]);

  const onPickFile = useCallback(
    async (list: FileList | null) => {
      const f = list?.[0];
      if (!f) return;
      await submitBlob(f, "upload");
    },
    [submitBlob],
  );

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div className="verify-flow-backdrop" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && phase === "flow" && !busy && onClose()}>
      <div className="verify-flow-sheet" role="dialog" aria-modal="true" aria-labelledby="verify-flow-title" onMouseDown={(e) => e.stopPropagation()}>
        <div className="verify-flow-top">
          <button type="button" className="verify-flow-close" onClick={() => !busy && onClose()} aria-label={t("verification.flow.close")}>
            ×
          </button>
        </div>

        {phase === "success" ? (
          <div className="verify-flow-body verify-flow-body--center">
            <div className="verify-flow-check" aria-hidden>
              <svg viewBox="0 0 52 52" width="72" height="72">
                <circle className="verify-flow-check__circle" cx="26" cy="26" r="24" fill="none" strokeWidth="3" />
                <path className="verify-flow-check__mark" fill="none" strokeWidth="3" strokeLinecap="round" d="M14 27l8 8 16-16" />
              </svg>
            </div>
            <h2 id="verify-flow-title" className="verify-flow-title">
              {t("verification.flow.successTitle")}
            </h2>
            <p className="verify-flow-sub">{t("verification.flow.successSub")}</p>
          </div>
        ) : phase === "pending" ? (
          <div className="verify-flow-body verify-flow-body--center">
            <div className="verify-flow-spinner" aria-hidden />
            <h2 id="verify-flow-title" className="verify-flow-title">
              {t("verification.flow.pendingTitle")}
            </h2>
            <p className="verify-flow-sub">{t("verification.flow.pendingSub")}</p>
            <div style={{ marginTop: 18, display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setPhase("flow");
                  setSubmitError("");
                  stopStream();
                }}
              >
                {t("profile.verify.tryAgain")}
              </Button>
              <Button type="button" variant="primary" onClick={() => onClose()}>
                {t("verification.flow.close")}
              </Button>
            </div>
          </div>
        ) : phase === "uploading" ? (
          <div className="verify-flow-body verify-flow-body--center">
            <div className="verify-flow-spinner" aria-hidden />
            <h2 id="verify-flow-title" className="verify-flow-title">
              {t("verification.flow.uploading")}
            </h2>
          </div>
        ) : phase === "rejected" ? (
          <div className="verify-flow-body verify-flow-body--center">
            <h2 id="verify-flow-title" className="verify-flow-title">
              {t("verification.flow.rejectedTitle")}
            </h2>
            <p className="verify-flow-sub">{submitError || t("verification.flow.rejectedHint")}</p>
            <Button
              type="button"
              variant="primary"
              onClick={() => {
                setPhase("flow");
                setSubmitError("");
                stopStream();
              }}
            >
              {t("profile.verify.tryAgain")}
            </Button>
          </div>
        ) : (
          <div className="verify-flow-body">
            <h2 id="verify-flow-title" className="verify-flow-title">
              {t("verification.flow.onePhotoTitle")}
            </h2>
            <p className="verify-flow-sub">{t("verification.flow.onePhotoSub")}</p>

            <input
              ref={fileInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              style={{ position: "absolute", width: 1, height: 1, opacity: 0, pointerEvents: "none", overflow: "hidden", clip: "rect(0,0,0,0)" }}
              tabIndex={-1}
              aria-hidden
              onChange={(e) => void onPickFile(e.target.files)}
            />

            <div className="verify-flow-video-wrap">
              <video ref={videoRef} className="verify-flow-video" playsInline muted autoPlay />
              <div className="verify-flow-face-guide" aria-hidden />
            </div>
            {cameraError ? <p className="verify-flow-error">{cameraError}</p> : null}
            {submitError ? <p className="verify-flow-error">{submitError}</p> : null}

            <div className="verify-flow-actions verify-flow-actions--row">
              <Button type="button" variant="secondary" className="verify-flow-btn-secondary" disabled={busy} onClick={() => fileInputRef.current?.click()}>
                {t("verification.flow.choosePhoto")}
              </Button>
              {!streamReady ? (
                <Button type="button" variant="primary" className="verify-flow-btn-main" disabled={busy} onClick={() => void startCamera()}>
                  {t("verification.flow.openCamera")}
                </Button>
              ) : (
                <Button type="button" variant="primary" className="verify-flow-btn-main" disabled={busy} onClick={() => void onCaptureCamera()}>
                  {busy ? t("common.loading") : t("verification.flow.captureSelfie")}
                </Button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
