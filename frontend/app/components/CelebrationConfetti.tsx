"use client";

import type { CSSProperties } from "react";
import { useEffect, useMemo } from "react";

type Piece = { id: number; left: string; delay: string; duration: string; color: string; size: string; drift: string };

const COLORS = ["#7C5CFF", "#4F8CFF", "#E040B0", "#22F3FF", "#66E3A1", "#FF8A5B"];

function randomPieces(count: number): Piece[] {
  return Array.from({ length: count }, (_, i) => ({
    id: i,
    left: `${6 + Math.random() * 88}%`,
    delay: `${Math.random() * 0.35}s`,
    duration: `${1.6 + Math.random() * 0.9}s`,
    color: COLORS[i % COLORS.length]!,
    size: `${5 + Math.random() * 5}px`,
    drift: `${-40 + Math.random() * 80}px`,
  }));
}

type Props = {
  /** Fire once when mounted; call when animation window ends (parent may unmount via key). */
  onDone?: () => void;
};

/** Short burst; pointer-events none. */
export function CelebrationConfetti({ onDone }: Props) {
  const pieces = useMemo(() => randomPieces(28), []);

  useEffect(() => {
    const t = window.setTimeout(() => onDone?.(), 2400);
    return () => window.clearTimeout(t);
  }, [onDone]);

  return (
    <div className="celebration-confetti" aria-hidden>
      {pieces.map((p) => (
        <span
          key={p.id}
          className="celebration-confetti__piece"
          style={
            {
              left: p.left,
              animationDelay: p.delay,
              animationDuration: p.duration,
              background: p.color,
              width: p.size,
              height: p.size,
              ["--drift" as string]: p.drift,
            } as CSSProperties
          }
        />
      ))}
    </div>
  );
}
