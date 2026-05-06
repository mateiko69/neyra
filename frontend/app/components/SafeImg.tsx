"use client";

import type { CSSProperties } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PRIMARY_IMAGE_PLACEHOLDER, resolveMediaUrl } from "../../lib/media";

type Props = {
  /** Raw URL from API (relative, absolute, or empty). */
  src?: string | null;
  /** Second URL tried if primary fails (e.g. bundled demo main.jpg). */
  fallbackSrc?: string | null;
  /** Additional URLs tried in order after `fallbackSrc` (deduped; e.g. both gender JPGs). */
  extraFallbackSources?: readonly string[] | null;
  alt: string;
  className?: string;
  style?: CSSProperties;
  loading?: "lazy" | "eager";
  /** Applied to inner <img> for E2E (wrapper still receives `className`). */
  photoTestId?: string;
  /** Shown when the image cannot be loaded (neutral — never an auth/session message). */
  previewUnavailableText?: string;
};

type LoadMode = "live" | "dead";

function buildResolvedChain(src: unknown, fallbackSrc: unknown, extras: readonly string[] | null | undefined): string[] {
  const out: string[] = [];
  const push = (raw: unknown) => {
    const resolved = typeof raw === "string" ? resolveMediaUrl(raw.trim()) : "";
    if (resolved && !out.includes(resolved)) out.push(resolved);
  };
  push(src ?? "");
  push(fallbackSrc ?? "");
  for (const raw of extras ?? []) push(raw);
  return out;
}

export function SafeImg({
  src,
  fallbackSrc,
  extraFallbackSources,
  alt,
  className,
  photoTestId,
  style,
  loading = "lazy",
  previewUnavailableText,
}: Props) {
  const [mode, setMode] = useState<LoadMode>("live");
  const modeRef = useRef<LoadMode>("live");
  modeRef.current = mode;

  const extrasKey = (extraFallbackSources ?? []).join("\0");

  const chain = useMemo(
    () => buildResolvedChain(src, fallbackSrc, extraFallbackSources),
    [src, fallbackSrc, extrasKey],
  );

  const chainRef = useRef(chain);
  chainRef.current = chain;

  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setMode("live");
    modeRef.current = "live";
    setAttempt(0);
  }, [src, fallbackSrc, extrasKey]);

  const displaySrc = useMemo(() => {
    if (mode === "dead") return PRIMARY_IMAGE_PLACEHOLDER;
    const chosen =
      chain.length > 0 ? chain[Math.min(attempt, Math.max(0, chain.length - 1))] : "";
    if (!chosen) return PRIMARY_IMAGE_PLACEHOLDER;
    return chosen;
  }, [mode, chain, attempt]);

  const onError = useCallback(() => {
    if (modeRef.current === "dead") return;
    setAttempt((prev) => {
      const len = chainRef.current.length;
      const next = prev + 1;
      if (len <= 0) {
        setMode("dead");
        modeRef.current = "dead";
        return prev;
      }
      if (next < len) return next;
      setMode("dead");
      modeRef.current = "dead";
      return prev;
    });
  }, []);

  return (
    <span className={className} style={{ position: "relative", display: "block", ...style }}>
      <img
        data-testid={photoTestId}
        src={displaySrc || PRIMARY_IMAGE_PLACEHOLDER}
        alt={alt}
        style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
        loading={loading}
        onError={onError}
        decoding="async"
      />
      {mode === "dead" && previewUnavailableText ? (
        <span
          className="caption"
          style={{
            position: "absolute",
            left: 6,
            right: 6,
            bottom: 6,
            padding: "6px 8px",
            borderRadius: 8,
            background: "rgba(0,0,0,0.55)",
            color: "rgba(255,255,255,0.92)",
            fontSize: 11,
            lineHeight: 1.3,
            textAlign: "center",
            pointerEvents: "none",
          }}
        >
          {previewUnavailableText}
        </span>
      ) : null}
    </span>
  );
}
