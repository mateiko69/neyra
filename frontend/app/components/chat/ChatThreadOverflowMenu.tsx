"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useT } from "../i18n/I18nProvider";
import { getActionLabel } from "../../../lib/ui/actions";

type Props = {
  disabled?: boolean;
  partnerIgnored: boolean;
  canDelete: boolean;
  onDelete: () => void;
  onIgnore: () => void;
  onUnignore: () => void;
};

export function ChatThreadOverflowMenu({ disabled, partnerIgnored, canDelete, onDelete, onIgnore, onUnignore }: Props) {
  const { t, locale } = useT("ChatThreadOverflowMenu");
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (event: MouseEvent) => {
      const el = rootRef.current;
      if (!el || !(event.target instanceof Node) || el.contains(event.target)) return;
      setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const close = useCallback(() => setOpen(false), []);

  return (
    <div className="chat-thread-overflow" ref={rootRef}>
      <button
        type="button"
        className="chat-thread-overflow__trigger"
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={getActionLabel("chat.more", locale, t)}
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
      >
        ⋯
      </button>
      {open ? (
        <div className="chat-thread-overflow__menu" role="menu">
          {partnerIgnored ? (
            <>
              <button
                type="button"
                className="chat-thread-overflow__item"
                role="menuitem"
                disabled={!canDelete}
                onClick={() => (close(), void onDelete())}
              >
                {getActionLabel("chat.deleteMessage", locale, t)}
              </button>
              <button type="button" className="chat-thread-overflow__item" role="menuitem" onClick={() => (close(), void onUnignore())}>
                {t("chat.actions.unignore")}
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                className="chat-thread-overflow__item"
                role="menuitem"
                disabled={!canDelete}
                onClick={() => (close(), void onDelete())}
              >
                {getActionLabel("chat.deleteMessage", locale, t)}
              </button>
              <button type="button" className="chat-thread-overflow__item" role="menuitem" onClick={() => (close(), void onIgnore())}>
                {getActionLabel("chat.ignoreProfile", locale, t)}
              </button>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
