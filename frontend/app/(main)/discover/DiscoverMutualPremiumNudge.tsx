"use client";

import { useT } from "../../components/i18n/I18nProvider";

type Props = {
  onDismiss: () => void;
  onUnlock: () => void;
};

export function DiscoverMutualPremiumNudge({ onDismiss, onUnlock }: Props) {
  const { t } = useT("DiscoverMutualPremiumNudge");

  return (
    <div className="discover-mutual-nudge" role="region" aria-label={t("discover.mutualNudge.aria")}>
      <div className="discover-mutual-nudge__row">
        <p className="discover-mutual-nudge__text">{t("discover.mutualNudge.body")}</p>
        <div className="discover-mutual-nudge__actions">
          <button type="button" className="discover-mutual-nudge__cta" onClick={onUnlock}>
            {t("discover.mutualNudge.cta")}
          </button>
          <button type="button" className="discover-mutual-nudge__dismiss" onClick={onDismiss} aria-label={t("discover.mutualNudge.dismissAria")}>
            ×
          </button>
        </div>
      </div>
    </div>
  );
}
