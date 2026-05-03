"use client";

import { useEffect } from "react";
import { isI18nDebugEnabled, readI18nDebugMetadata } from "../../../lib/i18n";

const NODE_DEBUG_ATTR = "data-i18n-node-debug";

function clearNodeHighlights() {
  if (typeof document === "undefined") return;
  document.querySelectorAll<HTMLElement>(`[${NODE_DEBUG_ATTR}]`).forEach((element) => {
    element.removeAttribute(NODE_DEBUG_ATTR);
    element.classList.remove("i18n-debug-text", "i18n-debug-text--missing");
  });
}

function applyMissingNodeHighlights() {
  if (typeof document === "undefined") return;
  clearNodeHighlights();

  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const textNode = walker.currentNode;
    const meta = readI18nDebugMetadata(textNode.nodeValue);
    if (!meta?.missing) continue;

    const parent = textNode.parentElement;
    if (!parent) continue;

    parent.setAttribute(NODE_DEBUG_ATTR, "missing");
    parent.classList.add("i18n-debug-text", "i18n-debug-text--missing");
  }
}

export function I18nDebugRuntime() {
  useEffect(() => {
    if (!isI18nDebugEnabled() || typeof document === "undefined") return;

    document.documentElement.dataset.i18nDebug = "true";

    let animationFrameId = 0;
    const scheduleRefresh = () => {
      if (animationFrameId) return;
      animationFrameId = window.requestAnimationFrame(() => {
        animationFrameId = 0;
        applyMissingNodeHighlights();
      });
    };

    scheduleRefresh();

    const observer = new MutationObserver(scheduleRefresh);
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
    });

    return () => {
      if (animationFrameId) window.cancelAnimationFrame(animationFrameId);
      observer.disconnect();
      clearNodeHighlights();
      delete document.documentElement.dataset.i18nDebug;
    };
  }, []);

  return null;
}
