"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { getAuthBootstrapResult, getAuthMeSnapshot } from "../../../lib/auth/bootstrap";
import {
  NEYRA_PREMIUM_PLUS_PRICE_ID,
  NEYRA_PREMIUM_PRICE_ID,
  openCheckout,
} from "../../../lib/paddle";

function CheckIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="currentColor" aria-hidden>
      <path
        fillRule="evenodd"
        d="M16.704 4.153a.75.75 0 01.143 1.052l-7.5 9.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 6.951-8.803a.75.75 0 011.052-.143z"
        clipRule="evenodd"
      />
    </svg>
  );
}

export type NeyraPremiumPaywallProps = {
  /** Full-page scroll vs overlay modal shell */
  variant?: "page" | "modal";
  onClose?: () => void;
};

export function NeyraPremiumPaywall({ variant = "page", onClose }: NeyraPremiumPaywallProps) {
  const [busy, setBusy] = useState<"premium" | "plus" | null>(null);
  const [userId, setUserId] = useState<string | null>(null);

  useEffect(() => {
    const snap = getAuthMeSnapshot();
    const uid = snap?.user_id;
    if (uid !== undefined && uid !== null && String(uid).trim() !== "") {
      setUserId(String(uid));
      return;
    }
    void getAuthBootstrapResult().then(() => {
      const s = getAuthMeSnapshot();
      const u = s?.user_id;
      if (u !== undefined && u !== null && String(u).trim() !== "") setUserId(String(u));
    });
  }, []);

  const checkoutCustomData = useCallback(
    (planKey: "premium_monthly" | "premium_plus_monthly") => {
      const base: Record<string, string | number | boolean> = { plan_key: planKey };
      if (userId) base.user_id = userId;
      return base;
    },
    [userId],
  );

  const onPremium = useCallback(async () => {
    if (busy) return;
    setBusy("premium");
    try {
      await openCheckout(NEYRA_PREMIUM_PRICE_ID, 1, {
        customData: checkoutCustomData("premium_monthly"),
      });
    } finally {
      setBusy(null);
    }
  }, [busy, checkoutCustomData]);

  const onPlus = useCallback(async () => {
    if (busy || !NEYRA_PREMIUM_PLUS_PRICE_ID) return;
    setBusy("plus");
    try {
      await openCheckout(NEYRA_PREMIUM_PLUS_PRICE_ID, 1, {
        customData: checkoutCustomData("premium_plus_monthly"),
      });
    } finally {
      setBusy(null);
    }
  }, [busy, checkoutCustomData]);

  const plusConfigured = Boolean(NEYRA_PREMIUM_PLUS_PRICE_ID);

  const shellClass =
    variant === "modal"
      ? "tw-fixed tw-inset-0 tw-z-[100] tw-flex tw-items-start tw-justify-center tw-overflow-y-auto tw-bg-black/65 tw-backdrop-blur-md tw-px-4 tw-py-8 sm:tw-py-12"
      : "tw-min-h-[100dvh] tw-bg-neyra-bg tw-text-white";

  const innerClass =
    variant === "modal"
      ? "tw-relative tw-w-full tw-max-w-5xl tw-rounded-3xl tw-border tw-border-white/10 tw-bg-gradient-to-b tw-from-[#12151f] tw-to-[#090b10] tw-p-6 tw-shadow-paywall-glow sm:tw-p-10"
      : "tw-relative tw-mx-auto tw-w-full tw-max-w-5xl tw-px-4 tw-py-10 sm:tw-px-6 sm:tw-py-14";

  return (
    <div className={shellClass}>
      <div className={innerClass}>
        {variant === "modal" && onClose ? (
          <button
            type="button"
            onClick={onClose}
            className="tw-absolute tw-right-4 tw-top-4 tw-flex tw-h-10 tw-w-10 tw-items-center tw-justify-center tw-rounded-full tw-border tw-border-white/15 tw-bg-white/5 tw-text-white/80 tw-transition hover:tw-bg-white/10 hover:tw-text-white motion-safe:tw-duration-200"
            aria-label="Close"
          >
            <span className="tw-text-xl tw-leading-none">×</span>
          </button>
        ) : null}

        {variant === "page" ? (
          <div className="tw-mb-8 tw-flex tw-justify-center sm:tw-mb-10">
            <Link
              href="/"
              className="tw-text-sm tw-font-medium tw-text-white/55 tw-transition hover:tw-text-white/90 motion-safe:tw-duration-200"
            >
              ← Back
            </Link>
          </div>
        ) : null}

        {/* Hero */}
        <header className="tw-mx-auto tw-mb-12 tw-max-w-3xl tw-text-center sm:tw-mb-16">
          <p className="tw-mb-3 tw-inline-flex tw-rounded-full tw-border tw-border-violet-400/25 tw-bg-violet-500/10 tw-px-3 tw-py-1 tw-text-xs tw-font-semibold tw-tracking-wide tw-text-violet-200/90">
            NEYRA Premium
          </p>
          <h1 className="tw-mb-4 tw-bg-gradient-to-r tw-from-white tw-via-white tw-to-white/80 tw-bg-clip-text tw-text-3xl tw-font-bold tw-leading-tight tw-text-transparent sm:tw-text-4xl md:tw-text-[2.65rem] md:tw-leading-[1.12]">
            Stop guessing what to say. Start getting replies.
          </h1>
          <p className="tw-text-base tw-leading-relaxed tw-text-white/65 sm:tw-text-lg">
            NEYRA helps you turn matches into real conversations.
          </p>
        </header>

        {/* Plan cards */}
        <div className="tw-mx-auto tw-mb-14 tw-grid tw-max-w-4xl tw-gap-6 md:tw-mb-20 md:tw-grid-cols-2 md:tw-items-stretch md:tw-gap-8">
          {/* Premium */}
          <article
            className="tw-group tw-flex tw-flex-col tw-rounded-3xl tw-border tw-border-white/12 tw-bg-white/[0.04] tw-p-6 tw-shadow-lg tw-transition motion-safe:tw-duration-300 motion-safe:tw-ease-out hover:tw-border-white/20 hover:tw-bg-white/[0.06] hover:tw-shadow-xl md:tw-p-8 md:hover:tw-scale-[1.02]"
          >
            <div className="tw-mb-6">
              <h2 className="tw-text-xl tw-font-bold tw-tracking-tight">Premium</h2>
              <div className="tw-mt-3 tw-flex tw-baseline tw-gap-1 tw-text-white">
                <span className="tw-text-4xl tw-font-extrabold tw-tracking-tight">$9.99</span>
                <span className="tw-self-end tw-pb-1 tw-text-sm tw-font-medium tw-text-white/55">/month</span>
              </div>
            </div>
            <ul className="tw-mb-8 tw-flex tw-flex-1 tw-flex-col tw-gap-3 tw-text-sm tw-text-white/85">
              {["AI reply suggestions", "Conversation improvements", "Unlimited chats", "5-day free trial"].map((f) => (
                <li key={f} className="tw-flex tw-items-start tw-gap-2.5">
                  <CheckIcon className="tw-mt-0.5 tw-h-5 tw-w-5 tw-shrink-0 tw-text-emerald-400" />
                  <span>{f}</span>
                </li>
              ))}
            </ul>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => void onPremium()}
              className="tw-mt-auto tw-w-full tw-rounded-2xl tw-bg-gradient-to-r tw-from-violet-600 tw-to-fuchsia-600 tw-py-3.5 tw-text-base tw-font-bold tw-text-white tw-shadow-lg tw-transition hover:tw-brightness-110 active:tw-scale-[0.98] disabled:tw-opacity-60 motion-safe:tw-duration-200"
            >
              {busy === "premium" ? "Opening…" : "Start free trial"}
            </button>
          </article>

          {/* Premium+ */}
          <article
            className="tw-relative tw-z-[1] tw-flex tw-flex-col tw-rounded-3xl tw-border-2 tw-border-transparent tw-bg-gradient-to-br tw-from-[#1a1428] tw-via-[#12101c] tw-to-[#0c0a12] tw-p-6 tw-shadow-paywall-plus tw-ring-1 tw-ring-fuchsia-500/35 tw-transition motion-safe:tw-duration-300 motion-safe:tw-ease-out md:tw--my-2 md:tw-scale-[1.04] md:tw-p-8 md:hover:tw-scale-[1.05]"
            style={{
              backgroundImage:
                "linear-gradient(135deg, rgba(124,92,255,0.35), rgba(255,79,216,0.15)), linear-gradient(145deg, #1a1428, #12101c)",
            }}
          >
            <div
              className="tw-pointer-events-none tw-absolute tw-inset-0 tw-rounded-3xl tw-opacity-90"
              style={{
                background: "linear-gradient(135deg, rgba(124,92,255,0.2) 0%, transparent 45%, rgba(255,79,216,0.12) 100%)",
              }}
            />
            <div className="tw-relative">
              <span className="tw-mb-4 tw-inline-flex tw-rounded-full tw-bg-gradient-to-r tw-from-amber-500 tw-to-orange-500 tw-px-3 tw-py-1 tw-text-xs tw-font-bold tw-text-black tw-shadow-md">
                🔥 Most Popular
              </span>
              <h2 className="tw-text-xl tw-font-bold tw-tracking-tight">Premium+</h2>
              <div className="tw-mt-3 tw-flex tw-baseline tw-gap-1 tw-text-white">
                <span className="tw-text-4xl tw-font-extrabold tw-tracking-tight">$19.99</span>
                <span className="tw-self-end tw-pb-1 tw-text-sm tw-font-medium tw-text-white/55">/month</span>
              </div>
              <p className="tw-mt-2 tw-text-xs tw-font-medium tw-text-white/45">No trial — full power from day one</p>
            </div>
            <ul className="tw-relative tw-mb-8 tw-mt-6 tw-flex tw-flex-1 tw-flex-col tw-gap-3 tw-text-sm tw-text-white/90">
              {["Best AI replies", "Higher reply rate", "Priority profile visibility", "Advanced conversation insights"].map((f) => (
                <li key={f} className="tw-flex tw-items-start tw-gap-2.5">
                  <CheckIcon className="tw-mt-0.5 tw-h-5 tw-w-5 tw-shrink-0 tw-text-fuchsia-300" />
                  <span>{f}</span>
                </li>
              ))}
            </ul>
            <button
              type="button"
              disabled={busy !== null || !plusConfigured}
              title={!plusConfigured ? "Set NEXT_PUBLIC_NEYRA_PREMIUM_PLUS_PRICE_ID" : undefined}
              onClick={() => void onPlus()}
              className="tw-relative tw-mt-auto tw-w-full tw-rounded-2xl tw-bg-gradient-to-r tw-from-fuchsia-500 tw-via-violet-500 tw-to-cyan-400 tw-py-3.5 tw-text-base tw-font-bold tw-text-white tw-shadow-xl tw-transition hover:tw-brightness-110 active:tw-scale-[0.98] disabled:tw-cursor-not-allowed disabled:tw-opacity-50 motion-safe:tw-duration-200"
            >
              {busy === "plus" ? "Opening…" : !plusConfigured ? "Configure Premium+ price" : "Get Premium+"}
            </button>
          </article>
        </div>

        {/* Social proof */}
        <section className="tw-mx-auto tw-mb-14 tw-max-w-xl tw-text-center md:tw-mb-16">
          <p className="tw-text-sm tw-font-medium tw-leading-relaxed tw-text-white/55 sm:tw-text-base">
            Premium+ users get noticeably better responses.
          </p>
        </section>

        {/* AI demo */}
        <section className="tw-mx-auto tw-mb-14 tw-max-w-3xl md:tw-mb-16">
          <h3 className="tw-mb-6 tw-text-center tw-text-sm tw-font-semibold tw-uppercase tw-tracking-wider tw-text-white/45">
            See the difference
          </h3>
          <div className="tw-grid tw-gap-4 md:tw-grid-cols-2 md:tw-gap-6">
            <div className="tw-rounded-2xl tw-border tw-border-white/10 tw-bg-black/30 tw-p-5">
              <p className="tw-mb-2 tw-text-xs tw-font-semibold tw-uppercase tw-tracking-wide tw-text-white/40">Before</p>
              <p className="tw-text-sm tw-leading-relaxed tw-text-white/75">
                hey whats up
              </p>
            </div>
            <div className="tw-rounded-2xl tw-border tw-border-violet-400/30 tw-bg-gradient-to-br tw-from-violet-500/15 tw-to-fuchsia-500/10 tw-p-5 tw-shadow-inner">
              <p className="tw-mb-2 tw-text-xs tw-font-semibold tw-uppercase tw-tracking-wide tw-text-violet-300/90">After AI</p>
              <p className="tw-text-sm tw-leading-relaxed tw-text-white">
                Hey — your hiking pic caught my eye. What&apos;s the best trail you&apos;ve done lately?
              </p>
            </div>
          </div>
        </section>

        {/* Footer */}
        <footer className="tw-mx-auto tw-max-w-md tw-text-center">
          <p className="tw-text-sm tw-text-white/45">Cancel anytime. No commitment.</p>
          {variant === "page" ? (
            <p className="tw-mt-4 tw-text-xs tw-text-white/35">
              <Link href="/subscription" className="tw-underline tw-underline-offset-2 hover:tw-text-white/55">
                Compare all plans
              </Link>
            </p>
          ) : null}
        </footer>
      </div>
    </div>
  );
}
