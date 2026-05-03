"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { BACKEND_PUBLIC_URL } from "../../lib/apiBase";
import { i18nKey, resolveI18nText, type I18nText } from "../../lib/i18n/message";
import { PAGE_SECONDARY_FETCH_DELAY_MS, schedulePageLoad } from "../../lib/pageLoad";
import { loadSocialProviders, type SocialProvidersState } from "../../lib/socialProviders";
import { useT } from "./i18n/I18nProvider";
import { Button, Skeleton } from "./ui";

type Props = {
  onError: (message: NonNullable<I18nText>) => void;
  disabled?: boolean;
};

function GoogleMark() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="auth-social__icon auth-social__icon--google">
      <path
        fill="#EA4335"
        d="M12 10.2v3.9h5.5c-.2 1.3-1.5 3.9-5.5 3.9-3.3 0-6-2.7-6-6s2.7-6 6-6c1.9 0 3.2.8 3.9 1.5l2.6-2.5C16.9 3.5 14.7 2.5 12 2.5A9.5 9.5 0 1 0 12 21.5c5.5 0 9.1-3.8 9.1-9.2 0-.6-.1-1.1-.2-1.6H12Z"
      />
      <path
        fill="#4285F4"
        d="M3.6 7.7 6.8 10c.9-2.7 3.4-4.6 6.2-4.6 1.9 0 3.2.8 3.9 1.5l2.6-2.5C17.8 2.9 15.5 2 13 2 9.3 2 6 4.1 4.3 7.2Z"
      />
      <path
        fill="#FBBC05"
        d="M3 12c0 1.5.4 3 1.1 4.3l3.1-2.4c-.2-.6-.3-1.2-.3-1.9 0-.7.1-1.3.3-1.9L4.1 7.8A9.3 9.3 0 0 0 3 12Z"
      />
      <path
        fill="#34A853"
        d="M12 21.5c2.6 0 4.8-.9 6.4-2.4l-3-2.3c-.8.5-1.9.8-3.4.8-2.8 0-5.3-1.9-6.2-4.5l-3.2 2.4C6 19 8.8 21.5 12 21.5Z"
      />
    </svg>
  );
}

export function SocialAuthSection({ onError, disabled = false }: Props) {
  const router = useRouter();
  const { t } = useT("SocialAuthSection");
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  const [providerState, setProviderState] = useState<SocialProvidersState | null>(null);
  const [busy, setBusy] = useState(false);
  const [inlineError, setInlineError] = useState<I18nText>(null);

  useEffect(() => {
    let cancelled = false;
    const cancelLoad = schedulePageLoad(() => {
      void (async () => {
        setInlineError(null);
        const result = await loadSocialProviders();
        if (cancelled) return;
        setProviderState(result);
        if (result.failed) {
          setInlineError(i18nKey("auth.googleUnavailable"));
          return;
        }
        const p = result.providers;
        if (!p?.google || !p.google_client_id) {
          setInlineError(i18nKey("auth.googleUnavailable"));
        }
      })();
    }, PAGE_SECONDARY_FETCH_DELAY_MS);
    return () => {
      cancelled = true;
      cancelLoad();
    };
  }, []);

  const isLoading = providerState == null;
  const providers = providerState?.providers ?? null;
  const googleConfigured = Boolean(providers?.google && providers.google_client_id);
  const commonDisabled = disabled || busy;

  function startGoogle() {
    if (!googleConfigured) {
      onErrorRef.current(i18nKey("auth.googleUnavailable"));
      return;
    }
    setBusy(true);
    const nextPath = "/onboarding";
    const url = `${BACKEND_PUBLIC_URL}/api/v1/auth/social/google/start?next=${encodeURIComponent(nextPath)}`;
    window.location.assign(url);
  }

  const inlineErrorText = resolveI18nText(inlineError, t);

  return (
    <section className="auth-social" aria-live="polite" aria-busy={commonDisabled || isLoading}>
      {inlineErrorText ? <div className="auth-social__status auth-social__status--error">{inlineErrorText}</div> : null}

      <div className="auth-social__buttons">
        {isLoading ? <Skeleton className="auth-social__skeleton" /> : null}
        {!isLoading ? (
          <Button
            type="button"
            variant="primary"
            disabled={commonDisabled || !googleConfigured}
            onClick={() => startGoogle()}
            className="auth-social__button auth-social__button--google"
            aria-label={t("auth.continueWithGoogle")}
            title={!googleConfigured ? t("auth.googleUnavailable") : undefined}
          >
            <span className="auth-social__button-content">
              <GoogleMark />
              <span className="auth-social__button-label">{t("auth.continueWithGoogle")}</span>
            </span>
          </Button>
        ) : null}
      </div>
    </section>
  );
}

