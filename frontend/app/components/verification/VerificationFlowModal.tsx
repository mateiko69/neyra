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

function poseLabelKey(pose: string): string {
  switch ((pose || "").trim().toLowerCase()) {
    case "turn_head_left":
      return "verification.flow.pose.turnHeadLeft";
    case "smile":
      return "verification.flow.pose.smile";
    case "raise_hand":
      return "verification.flow.pose.raiseHand";
    default:
      return "verification.flow.pose.smile";
  }
}

async function captureBurst(video: HTMLVideoElement, count: number, gapMs: number): Promise<Blob[]> {
  const w = video.videoWidth;
  const h = video.videoHeight;
  if (w < 2 || h < 2) throw new Error("video-not-ready");
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("no-ctx");
  const out: Blob[] = [];
  for (let i = 0; i < count; i++) {
    if (i > 0) await new Promise((r) => setTimeout(r, gapMs));
    ctx.drawImage(video, 0, 0, w, h);
    const blob = await new Promise<Blob>((res, rej) => {
      canvas.toBlob((b) => (b ? res(b) : rej(new Error("blob"))), "image/jpeg", 0.85);
    });
    out.push(blob);
  }
  return out;
}

export function VerificationFlowModal({ open, onClose, onComplete }: Props) {
  const { t } = useT("VerificationFlowModal");
  const [step, setStep] = useState(1);
  const [poseChallenge, setPoseChallenge] = useState("smile");
  const [startError, setStartError] = useState("");
  const [camError, setCamError] = useState("");
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [phase, setPhase] = useState<"flow" | "uploading" | "success" | "pending" | "rejected">("flow");
  const [baselineFrames, setBaselineFrames] = useState<Blob[]>([]);
  const [streamReady, setStreamReady] = useState(false);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

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
      setStep(1);
      setBaselineFrames([]);
      setStartError("");
      setCamError("");
      setSubmitError("");
      setPhase("flow");
      setBusy(false);
      setStreamReady(false);
      return;
    }
    setStartError("");
    void apiFetch("/verify/start", {
      method: "POST",
      body: JSON.stringify({}),
      metaReason: "verify-start",
      skipThrottle: true,
      skipCache: true,
    })
      .then((r) => {
        const o = r as VerifyStartResponse;
        const p = String(o.pose_challenge || "").trim();
        setPoseChallenge(p || "smile");
      })
      .catch((e: unknown) => {
        setStartError(resolveI18nText(apiFailureToI18nText(e, t, "verification.flow.errors.startFailed", formatApiError), t));
      });
    return () => stopStream();
  }, [open, stopStream, t]);

  const startCamera = useCallback(async () => {
    setCamError("");
    if (!navigator.mediaDevices?.getUserMedia) {
      setCamError(t("profile.verify.errors.browserNoCamera"));
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
      setCamError(t("profile.verify.errors.cameraDenied"));
      setStreamReady(false);
    }
  }, [stopStream, t]);

  const onCaptureBaseline = useCallback(async () => {
    const v = videoRef.current;
    if (!v) return;
    setBusy(true);
    setSubmitError("");
    try {
      const blobs = await captureBurst(v, 6, 160);
      setBaselineFrames(blobs);
      setStep(2);
    } catch {
      setSubmitError(t("profile.verify.errors.notEnoughFrames"));
    } finally {
      setBusy(false);
    }
  }, [t]);

  const onCapturePose = useCallback(async () => {
    const v = videoRef.current;
    if (!v) return;
    setBusy(true);
    setSubmitError("");
    try {
      const poseBlobs = await captureBurst(v, 6, 160);
      const all = [...baselineFrames, ...poseBlobs];
      if (all.length < 6) {
        setSubmitError(t("profile.verify.errors.notEnoughFrames"));
        return;
      }
      setPhase("uploading");
      const fd = new FormData();
      fd.append("verification_source", "camera");
      fd.append("pose_challenge", poseChallenge);
      fd.append("captured_at", new Date().toISOString());
      all.forEach((b, i) => {
        fd.append("frames", b, `frame_${i}.jpg`);
      });
      const raw = await apiUpload("/verify/submit", fd, { metaReason: "verify-submit" });
      const res = raw as SubmitResponse;
      const st = String(res.status || res.verification_status || "").toLowerCase();
      if (st === "approved") {
        setPhase("success");
        stopStream();
        window.setTimeout(() => {
          onComplete();
          onClose();
        }, 2200);
        return;
      }
      if (st === "pending") {
        setPhase("pending");
        stopStream();
        window.setTimeout(() => {
          onComplete();
          onClose();
        }, 2000);
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
  }, [baselineFrames, onClose, onComplete, poseChallenge, stopStream, t]);

  if (!open || typeof document === "undefined") return null;

  const progressLabel = t("verification.flow.progress", { current: Math.min(step, 3), total: 3 });

  return createPortal(
    <div className="verify-flow-backdrop" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && phase === "flow" && !busy && onClose()}>
      <div className="verify-flow-sheet" role="dialog" aria-modal="true" aria-labelledby="verify-flow-title" onMouseDown={(e) => e.stopPropagation()}>
        <div className="verify-flow-top">
          <button type="button" className="verify-flow-close" onClick={() => !busy && onClose()} aria-label={t("verification.flow.close")}>
            ×
          </button>
          <div className="verify-flow-progress">{progressLabel}</div>
        </div>

        {startError ? (
          <div className="verify-flow-body">
            <p className="verify-flow-error">{startError}</p>
            <Button type="button" variant="primary" onClick={() => onClose()}>
              {t("common.close")}
            </Button>
          </div>
        ) : phase === "success" ? (
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
                setStep(1);
                setBaselineFrames([]);
                setSubmitError("");
                stopStream();
                void apiFetch("/verify/start", {
                  method: "POST",
                  body: JSON.stringify({}),
                  metaReason: "verify-restart",
                  skipThrottle: true,
                  skipCache: true,
                })
                  .then((r) => {
                    const o = r as VerifyStartResponse;
                    setPoseChallenge(String(o.pose_challenge || "smile"));
                  })
                  .catch(() => {});
              }}
            >
              {t("profile.verify.tryAgain")}
            </Button>
          </div>
        ) : (
          <div className="verify-flow-body">
            {step === 1 ? (
              <>
                <h2 id="verify-flow-title" className="verify-flow-title">
                  {t("verification.flow.step1Title")}
                </h2>
                <p className="verify-flow-sub">{t("verification.flow.step1Sub")}</p>
              </>
            ) : null}
            {step === 2 ? (
              <>
                <h2 id="verify-flow-title" className="verify-flow-title">
                  {t("verification.flow.step2Title")}
                </h2>
                <p className="verify-flow-pose">{t(poseLabelKey(poseChallenge))}</p>
                <p className="verify-flow-sub">{t("verification.flow.step2Sub")}</p>
              </>
            ) : null}

            <div className="verify-flow-video-wrap">
              <video ref={videoRef} className="verify-flow-video" playsInline muted autoPlay />
              <div className="verify-flow-face-guide" aria-hidden />
            </div>
            {camError ? <p className="verify-flow-error">{camError}</p> : null}
            {submitError ? <p className="verify-flow-error">{submitError}</p> : null}

            {step === 1 ? (
              <div className="verify-flow-actions">
                {!streamReady ? (
                  <Button type="button" variant="primary" className="verify-flow-btn-main" onClick={() => void startCamera()}>
                    {t("verification.flow.openCamera")}
                  </Button>
                ) : (
                  <Button type="button" variant="primary" className="verify-flow-btn-main" disabled={busy} onClick={() => void onCaptureBaseline()}>
                    {busy ? t("common.loading") : t("verification.flow.continue")}
                  </Button>
                )}
              </div>
            ) : null}

            {step === 2 ? (
              <div className="verify-flow-actions verify-flow-actions--row">
                <Button type="button" variant="secondary" className="verify-flow-btn-secondary" disabled={busy} onClick={() => setStep(1)}>
                  {t("common.back")}
                </Button>
                <Button type="button" variant="primary" className="verify-flow-btn-main" disabled={busy} onClick={() => void onCapturePose()}>
                  {busy ? t("common.loading") : t("verification.flow.capturePose")}
                </Button>
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}
