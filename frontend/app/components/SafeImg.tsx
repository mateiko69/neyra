"use client";

import type { CSSProperties } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PRIMARY_IMAGE_PLACEHOLDER, resolveMediaUrl } from "../../lib/media";

type Props = {
  /** Raw URL from API (relative, absolute, or empty). */
  src?: string | null;
  /** Second URL tried if primary fails (e.g. bundled demo main.jpg). */
  fallbackSrc?: string | null;
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

export function SafeImg({
  src,
  fallbackSrc,
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

  const resolvedPrimary = useMemo(() => resolveMediaUrl(src?.trim() || ""), [src]);
  const resolvedFallback = useMemo(
    () => (fallbackSrc?.trim() ? resolveMediaUrl(fallbackSrc.trim()) : ""),
    [fallbackSrc],
  );

  const [useFallback, setUseFallback] = useState(false);

  useEffect(() => {
    setMode("live");
    modeRef.current = "live";
    setUseFallback(false);
  }, [src, fallbackSrc]);

  const displaySrc = useMemo(() => {
    if (mode === "dead") return PRIMARY_IMAGE_PLACEHOLDER;
    const primary = resolvedPrimary;
    const fb = resolvedFallback;
    const chosen = useFallback && fb ? fb : primary || fb;
    if (!chosen) return PRIMARY_IMAGE_PLACEHOLDER;
    return chosen;
  }, [mode, resolvedPrimary, resolvedFallback, useFallback]);

  const onError = useCallback(() => {
    if (modeRef.current === "dead") return;
    if (!useFallback && resolvedFallback && resolvedPrimary && resolvedFallback !== resolvedPrimary) {
      setUseFallback(true);
      modeRef.current = "live";
      setMode("live");
      return;
    }
    setMode("dead");
    modeRef.current = "dead";
  }, [resolvedFallback, resolvedPrimary, useFallback]);

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
