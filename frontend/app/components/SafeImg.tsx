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
  onFinalError?: () => void;
};

type LoadMode = "live" | "dead";

function appendCacheBust(url: string, nonce: number): string {
  if (nonce <= 0) return url;
  if (!/^https?:\/\//i.test(url)) return url;
  try {
    const u = new URL(url);
    u.searchParams.set("_neyraRetry", String(nonce));
    return u.toString();
  } catch {
    return `${url}${url.includes("?") ? "&" : "?"}_neyraRetry=${nonce}`;
  }
}

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
  onFinalError,
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
  /** One cache-busting reload per chain step for transient CDN / TLS blips. */
  const [bustNonce, setBustNonce] = useState(0);

  useEffect(() => {
    setMode("live");
    modeRef.current = "live";
    setAttempt(0);
    setBustNonce(0);
  }, [src, fallbackSrc, extrasKey]);

  useEffect(() => {
    setBustNonce(0);
  }, [attempt]);

  const displaySrc = useMemo(() => {
    if (mode === "dead") return PRIMARY_IMAGE_PLACEHOLDER;
    const chosen =
      chain.length > 0 ? chain[Math.min(attempt, Math.max(0, chain.length - 1))] : "";
    if (!chosen) return PRIMARY_IMAGE_PLACEHOLDER;
    return appendCacheBust(chosen, bustNonce);
  }, [mode, chain, attempt, bustNonce]);

  const onError = useCallback(() => {
    if (modeRef.current === "dead") return;
    const len = chainRef.current.length;
    if (len <= 0) {
      setMode("dead");
      modeRef.current = "dead";
      return;
    }
    const idx = Math.min(attempt, Math.max(0, len - 1));
    const chosen = chainRef.current[idx] || "";
    if (bustNonce < 1 && /^https?:\/\//i.test(chosen)) {
      setBustNonce(1);
      return;
    }
    const next = attempt + 1;
    setBustNonce(0);
    if (next < len) {
      setAttempt(next);
      return;
    }
    onFinalError?.();
    setMode("dead");
    modeRef.current = "dead";
  }, [attempt, bustNonce, onFinalError]);

  return (
    <span className={className} style={{ position: "relative", display: "block", ...style }}>
      <img
        key={`${attempt}:${bustNonce}:${displaySrc}`}
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
