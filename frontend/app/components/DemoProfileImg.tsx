"use client";

import type { CSSProperties } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { resolveMediaUrl } from "../../lib/media";

type Props = {
  src?: string | null;
  alt: string;
  className?: string;
  style?: CSSProperties;
  loading?: "lazy" | "eager";
  photoTestId?: string;
  /** After one failed load + one same-URL retry, parent drops the profile from the deck. */
  onFatalError?: () => void;
};

/**
 * Loads demo primary photo: same URL is attempted twice (browser cache may recover).
 * No placeholder surface — parent must remove card if `onFatalError` fires.
 */
export function DemoProfileImg({ src, alt, className, style, loading = "lazy", photoTestId, onFatalError }: Props) {
  const resolved = useMemo(() => resolveMediaUrl(String(src || "").trim()), [src]);
  const [attempt, setAttempt] = useState(0);
  const reportedRef = useRef(false);

  useEffect(() => {
    setAttempt(0);
    reportedRef.current = false;
  }, [resolved]);

  const imgSrc = useMemo(() => {
    if (!resolved) return "";
    if (attempt === 0) return resolved;
    const join = resolved.includes("?") ? "&" : "?";
    return `${resolved}${join}r=${attempt}`;
  }, [resolved, attempt]);

  const onError = useCallback(() => {
    if (!resolved) {
      if (!reportedRef.current) {
        reportedRef.current = true;
        onFatalError?.();
      }
      return;
    }
    if (attempt === 0) {
      setAttempt(1);
      return;
    }
    if (!reportedRef.current) {
      reportedRef.current = true;
      onFatalError?.();
    }
  }, [attempt, onFatalError, resolved]);

  if (!resolved) {
    return null;
  }

  return (
    <span className={className} style={{ position: "relative", display: "block", ...style }}>
      <img
        data-testid={photoTestId}
        src={imgSrc}
        alt={alt}
        style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
        loading={loading}
        decoding="async"
        onError={onError}
      />
    </span>
  );
}
