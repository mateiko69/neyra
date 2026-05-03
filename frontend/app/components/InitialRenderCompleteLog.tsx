"use client";

import { useEffect } from "react";

/** One-shot client marker after first paint + hydration (no blocking work here). */
export function InitialRenderCompleteLog() {
  useEffect(() => {
    console.log("[neyra] initial render complete");
  }, []);
  return null;
}
