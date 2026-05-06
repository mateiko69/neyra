"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { FORCE_AI_VISIBLE, logAiGate } from "../../../lib/aiDebug";
import { useT } from "../i18n/I18nProvider";
import { Button } from "../ui";
import { getActionLabel } from "../../../lib/ui/actions";

export type VoiceDraft = {
  blob: Blob;
  mime: string;
  previewUrl: string;
  durationMs: number | null;
};

type ChatComposerProps = {
  value: string;
  sending: boolean;
  isSendingVoice?: boolean;
  voiceSendPhase?: "idle" | "uploading" | "posting" | "failed";
  voiceSendError?: string;
  disabled?: boolean;
  error?: string;
  replyTo?: { label: string } | null;
  onCancelReply?: () => void;
  onChange: (value: string) => void;
  onSend: () => void;
  onSendVoice?: (draft: VoiceDraft, caption: string) => Promise<{ ok: true } | { ok: false; error: string }>;
  onToggleAi?: () => void;
  aiActive?: boolean;
  aiLoading?: boolean;
  aiSuggestionLocale?: string;
  onAiSuggestionLocaleChange?: (next: string) => void;
  autoFocus?: boolean;
  /** Increment to focus the textarea (e.g. after AI inserts an opener). */
  focusComposerKey?: number;
  /** Increment to play a one-shot “text landed” motion on the textarea. */
  draftBurstKey?: number;
  /** Short pulse glow on the primary send control (e.g. after AI insert). */
  pulseSend?: boolean;
  /** Increment after a successful send — subtle “message landed” motion. */
  sendSuccessKey?: number;
};

export function ChatComposer({
  value,
  sending,
  isSendingVoice = false,
  voiceSendPhase = "idle",
  voiceSendError,
  disabled = false,
  error,
  replyTo,
  onCancelReply,
  onChange,
  onSend,
  onSendVoice,
  onToggleAi,
  aiActive = false,
  aiLoading = false,
  aiSuggestionLocale = "auto",
  onAiSuggestionLocaleChange,
  autoFocus = false,
  focusComposerKey = 0,
  draftBurstKey = 0,
  pulseSend = false,
  sendSuccessKey = 0,
}: ChatComposerProps) {
  const { t, locale } = useT("ChatComposer");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const lastFocusKeyRef = useRef(0);
  const [draftBurst, setDraftBurst] = useState(false);
  const [sendBurst, setSendBurst] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const recordedChunksRef = useRef<BlobPart[]>([]);
  const [voiceDraft, setVoiceDraft] = useState<VoiceDraft | null>(null);
  const [recording, setRecording] = useState(false);
  const [recordError, setRecordError] = useState<string | null>(null);
  const [voiceDraftError, setVoiceDraftError] = useState<string | null>(null);
  const [previewPlaying, setPreviewPlaying] = useState(false);
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);

  useLayoutEffect(() => {
    const element = textareaRef.current;
    if (!element) return;
    element.style.height = "0px";
    element.style.height = `${Math.min(element.scrollHeight, 180)}px`;
  }, [value]);

  useEffect(() => {
    if (!autoFocus) return;
    const el = textareaRef.current;
    if (!el) return;
    requestAnimationFrame(() => {
      try {
        el.focus();
        const end = el.value.length;
        el.setSelectionRange(end, end);
      } catch {
        /* ignore */
      }
    });
  }, [autoFocus]);

  useEffect(() => {
    if (!focusComposerKey || focusComposerKey === lastFocusKeyRef.current) return;
    lastFocusKeyRef.current = focusComposerKey;
    const el = textareaRef.current;
    if (!el) return;
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        try {
          el.focus();
          const end = el.value.length;
          el.setSelectionRange(end, end);
        } catch {
          /* ignore */
        }
      });
    });
  }, [focusComposerKey]);

  useEffect(() => {
    if (!draftBurstKey) return;
    setDraftBurst(true);
    const t = window.setTimeout(() => setDraftBurst(false), 700);
    return () => window.clearTimeout(t);
  }, [draftBurstKey]);

  useEffect(() => {
    if (!sendSuccessKey) return;
    setSendBurst(true);
    const t = window.setTimeout(() => setSendBurst(false), 650);
    return () => window.clearTimeout(t);
  }, [sendSuccessKey]);

  const canRecord = useMemo(() => {
    if (typeof window === "undefined") return false;
    return Boolean(navigator.mediaDevices?.getUserMedia) && typeof MediaRecorder !== "undefined";
  }, []);
  const trimmedValue = useMemo(() => (value ?? "").trim(), [value]);
  const aiLocaleOptions = useMemo(
    () => [
      ["auto", t("chat.aiLanguage.auto")],
      ["en", t("chat.aiLanguage.english")],
      ["uk", t("chat.aiLanguage.ukrainian")],
      ["es", t("chat.aiLanguage.spanish")],
      ["pt", t("chat.aiLanguage.portuguese")],
      ["fr", t("chat.aiLanguage.french")],
      ["de", t("chat.aiLanguage.german")],
      ["it", t("chat.aiLanguage.italian")],
      ["pl", t("chat.aiLanguage.polish")],
      ["cs", t("chat.aiLanguage.czech")],
      ["nl", t("chat.aiLanguage.dutch")],
      ["tr", t("chat.aiLanguage.turkish")],
      ["ar", t("chat.aiLanguage.arabic")],
      ["hi", t("chat.aiLanguage.hindi")],
      ["zh", t("chat.aiLanguage.chinese")],
      ["ja", t("chat.aiLanguage.japanese")],
      ["ko", t("chat.aiLanguage.korean")],
    ],
    [t],
  );

  useEffect(() => {
    logAiGate("chat-composer", {
      forceVisible: FORCE_AI_VISIBLE,
      aiAssistToggleActive: Boolean(aiActive),
      hasDraft: Boolean(trimmedValue),
      disabled,
      sending,
      isSendingVoice,
    });
  }, [aiActive, disabled, isSendingVoice, sending, trimmedValue]);

  function pickMime(): string {
    if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") {
      return "";
    }
    const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
    for (const mime of candidates) {
      if (MediaRecorder.isTypeSupported(mime)) return mime;
    }
    return "";
  }

  function clearVoiceDraft() {
    setRecordError(null);
    setVoiceDraftError(null);
    setPreviewPlaying(false);
    if (previewAudioRef.current) {
      previewAudioRef.current.pause();
      previewAudioRef.current.currentTime = 0;
    }
    setVoiceDraft((current) => {
      if (current?.previewUrl) URL.revokeObjectURL(current.previewUrl);
      return null;
    });
  }

  async function startRecording() {
    if (!canRecord || disabled || sending || isSendingVoice || recording) return;
    clearVoiceDraft();
    setRecordError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = pickMime();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      mediaRecorderRef.current = recorder;
      recordedChunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) recordedChunksRef.current.push(event.data);
      };
      recorder.onerror = () => {
        setRecordError(t("chat.composer.voice.errorGeneric"));
      };
      recorder.onstop = () => {
        const tracks = stream.getTracks();
        for (const track of tracks) track.stop();
        const blob = new Blob(recordedChunksRef.current, { type: recorder.mimeType || mimeType || "audio/webm" });
        recordedChunksRef.current = [];
        const previewUrl = URL.createObjectURL(blob);
        setVoiceDraftError(null);
        setVoiceDraft({ blob, mime: blob.type || recorder.mimeType || mimeType || "audio/webm", previewUrl, durationMs: null });
      };

      recorder.start();
      setRecording(true);
    } catch {
      setRecordError(t("chat.composer.voice.errorPermission"));
    }
  }

  function stopRecording() {
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === "inactive") return;
    setRecording(false);
    recorder.stop();
    mediaRecorderRef.current = null;
  }

  function formatDuration(durationMs: number | null): string | null {
    if (durationMs == null || !Number.isFinite(durationMs)) return null;
    const totalSeconds = Math.max(0, Math.round(durationMs / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
  }

  async function handleSendClick() {
    if (voiceDraft && onSendVoice) {
      if (isSendingVoice) return;
      setVoiceDraftError(null);
      const result = await onSendVoice(voiceDraft, value.trim());
      if (result.ok) {
        clearVoiceDraft();
      } else {
        setVoiceDraftError(("error" in result ? result.error : "") || t("chat.composer.voice.errorGeneric"));
      }
      return;
    }
    onSend();
  }

  function togglePreviewPlay() {
    const audio = previewAudioRef.current;
    if (!audio || !voiceDraft) return;
    if (!previewPlaying) {
      audio.play().catch(() => {});
      setPreviewPlaying(true);
    } else {
      audio.pause();
      setPreviewPlaying(false);
    }
  }

  return (
    <div className="chat-composer">
      {voiceDraft ? (
        <div className="chat-composer__voice">
          <audio
            ref={previewAudioRef}
            preload="metadata"
            src={voiceDraft.previewUrl}
            onLoadedMetadata={(event) => {
              const el = event.currentTarget;
              if (!Number.isFinite(el.duration)) return;
              const durationMs = Math.round(el.duration * 1000);
              setVoiceDraft((current) => (current ? { ...current, durationMs } : current));
            }}
            onEnded={() => setPreviewPlaying(false)}
            onPause={() => setPreviewPlaying(false)}
            style={{ display: "none" }}
          />
          <button
            type="button"
            className="chat-voice-ui__play"
            onClick={togglePreviewPlay}
            disabled={disabled || sending || isSendingVoice}
            aria-label={previewPlaying ? t("chat.composer.voice.pause") : t("chat.composer.voice.play")}
          >
            {previewPlaying ? "❚❚" : "▶"}
          </button>
          <div className="chat-composer__voice-meta">
            <div className="chat-composer__voice-label">{t("chat.composer.voice.preview")}</div>
            <div className="chat-composer__voice-duration">{formatDuration(voiceDraft.durationMs) ?? "—"}</div>
          </div>
          <button
            type="button"
            className="chat-composer__voice-delete"
            onClick={clearVoiceDraft}
            aria-label={t("chat.composer.voice.delete")}
            disabled={disabled || sending || isSendingVoice}
          >
            ×
          </button>
        </div>
      ) : null}

      {replyTo ? (
        <div className="chat-composer__reply">
          <div className="chat-composer__reply-label">{replyTo.label}</div>
          {onCancelReply ? (
            <button
              type="button"
              className="chat-composer__reply-cancel"
              onClick={onCancelReply}
              aria-label={t("chat.composer.cancelReply")}
            >
              ×
            </button>
          ) : null}
        </div>
      ) : null}

      <textarea
        ref={textareaRef}
        data-testid="chat-composer-input"
        className={[
          "chat-composer__input",
          "w-full text-white placeholder:text-gray-400 bg-[#0f0f12] caret-white",
          draftBurst ? "chat-composer__input--draft-burst" : "",
          sendBurst ? "chat-composer__input--send-burst" : "",
        ]
          .filter(Boolean)
          .join(" ")}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            if (!disabled && !sending && !isSendingVoice && (value.trim() || voiceDraft)) void handleSendClick();
          }
        }}
        placeholder={t("chat.placeholder")}
        disabled={disabled || sending || isSendingVoice}
        rows={1}
      />

      <div className="chat-composer__footer">
        <div className="chat-composer__meta">
          <div className="chat-composer__hint">{t("chat.composer.hint")}</div>
          {error ? <div className="chat-composer__error">{error}</div> : null}
          {recordError ? <div className="chat-composer__error">{recordError}</div> : null}
          {voiceSendError ? <div className="chat-composer__error">{voiceSendError}</div> : null}
          {voiceDraftError ? <div className="chat-composer__error">{voiceDraftError}</div> : null}
        </div>

        {onToggleAi ? (
          <label className="chat-composer__ai-locale">
            <span className="chat-composer__ai-locale-label">{t("chat.aiLanguage.label")}</span>
            <select
              className="chat-composer__ai-locale-select"
              value={aiSuggestionLocale || "auto"}
              onChange={(event) => onAiSuggestionLocaleChange?.(String(event.target.value || "auto"))}
              disabled={disabled || sending || isSendingVoice}
              aria-label={t("chat.aiLanguage.label")}
            >
              {aiLocaleOptions.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        {onToggleAi ? (
          <button
            type="button"
            data-testid="chat-ai-button"
            className={["chat-composer__ai", aiActive ? "chat-composer__ai--active" : ""].filter(Boolean).join(" ")}
            onClick={onToggleAi}
            disabled={disabled || sending || isSendingVoice || aiLoading}
            aria-label={aiActive ? t("chat.composer.ai.ariaHide") : t("chat.composer.ai.ariaShow")}
            aria-busy={aiLoading}
          >
            <span className="chat-composer__ai-icon" aria-hidden>
              ✨
            </span>
            <span className="chat-composer__ai-label">{getActionLabel("chat.ai", locale, t)}</span>
          </button>
        ) : null}

        {isSendingVoice ? (
          <div className="chat-composer__voice-sending" aria-label={t("chat.composer.voice.uploading")}>
            <span className="chat-spinner" aria-hidden />
            <span className="chat-composer__voice-sending-label">
              {voiceSendPhase === "posting" ? t("chat.composer.voice.sending") : t("chat.composer.voice.uploading")}
            </span>
          </div>
        ) : null}

        {canRecord ? (
          <button
            type="button"
            className={[
              "chat-composer__mic",
              recording ? "chat-composer__mic--recording" : "",
              voiceDraft ? "chat-composer__mic--has-draft" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            onClick={() => (recording ? stopRecording() : startRecording())}
            disabled={disabled || sending || isSendingVoice}
            aria-label={recording ? t("chat.composer.voice.stop") : t("chat.composer.voice.record")}
          >
            {recording ? "■" : "🎤"}
          </button>
        ) : null}

        <Button
          type="button"
          variant="primary"
          data-testid="chat-send-button"
          className={["chat-composer__send", pulseSend ? "chat-composer__send--pulse" : ""].filter(Boolean).join(" ")}
          onClick={() => void handleSendClick()}
          disabled={disabled || sending || isSendingVoice || (!value.trim() && !voiceDraft)}
        >
          {sending ? t("chat.composer.sending") : getActionLabel("chat.send", locale, t)}
        </Button>
      </div>
    </div>
  );
}
