"use client";

import { useT } from "../i18n/I18nProvider";
import { Button } from "../ui";

type Props = {
  disabled?: boolean;
  onSend: () => void;
  onEdit: () => void;
  onShare: () => void;
  onTryAnother: () => void;
};

export function ChatOpenerQuickBar({ disabled = false, onSend, onEdit, onShare, onTryAnother }: Props) {
  const { t } = useT("ChatOpenerQuickBar");

  return (
    <div className="chat-opener-quick-bar" role="toolbar" aria-label={t("chat.openerQuickBar.aria")}>
      <Button type="button" variant="primary" className="chat-opener-quick-bar__send" disabled={disabled} onClick={onSend}>
        {t("chat.openerQuickBar.send")}
      </Button>
      <Button type="button" variant="secondary" disabled={disabled} onClick={onEdit}>
        {t("chat.openerQuickBar.edit")}
      </Button>
      <Button type="button" variant="secondary" disabled={disabled} onClick={onShare}>
        <span className="chat-opener-quick-bar__share-label">{t("chat.openerQuickBar.share")}</span>
        <span className="chat-opener-quick-bar__share-hot" aria-hidden>
          🔥
        </span>
      </Button>
      <Button type="button" variant="ghost" disabled={disabled} onClick={onTryAnother}>
        {t("chat.openerQuickBar.tryAnother")}
      </Button>
    </div>
  );
}
