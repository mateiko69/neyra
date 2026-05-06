import type { Metadata } from "next";
import Link from "next/link";

export const dynamic = "force-static";

export const metadata: Metadata = {
  title: "Plans & pricing — NEYRA",
  description: "Compare Free, Premium, and Premium+ for NEYRA. Subscriptions renew monthly until cancelled.",
};

export default function PremiumPage() {
  return (
    <div className="public-marketing-page">
      <section className="public-marketing-hero">
        <div className="public-marketing-section-label">Pricing</div>
        <h1>Plans for every pace</h1>
        <p className="public-marketing-lede">
          NEYRA combines discovery and chat with an AI dating assistant. Paid tiers add deeper coaching and higher AI limits.
          Outcomes depend on real people and mutual interest — we never promise guaranteed matches or replies.
        </p>
      </section>

      <div className="public-plan-grid" style={{ marginBottom: 28 }}>
        <div className="public-plan-card">
          <div className="public-marketing-section-label">Starter</div>
          <h2 className="h2" style={{ margin: "4px 0 0", fontSize: "1.35rem", fontWeight: 950 }}>
            Free
          </h2>
          <div className="public-plan-price">$0</div>
          <ul>
            <li>Create your profile and browse discovery</li>
            <li>Chat when there is mutual interest</li>
            <li>Limited AI assists per day for prompts and coaching</li>
          </ul>
        </div>

        <div className="public-plan-card public-plan-card--featured">
          <div className="public-marketing-section-label">Most popular</div>
          <h2 className="h2" style={{ margin: "4px 0 0", fontSize: "1.35rem", fontWeight: 950 }}>
            Premium
          </h2>
          <div className="public-plan-price">$9.99 / month</div>
          <ul>
            <li>Higher AI limits for drafting and date coaching</li>
            <li>Richer personalization inside the assistant</li>
            <li>Access to premium profile and experience features as we release them</li>
          </ul>
        </div>

        <div className="public-plan-card">
          <div className="public-marketing-section-label">Power users</div>
          <h2 className="h2" style={{ margin: "4px 0 0", fontSize: "1.35rem", fontWeight: 950 }}>
            Premium+
          </h2>
          <div className="public-plan-price">$19.99 / month</div>
          <ul>
            <li>Top AI limits and the newest assistant capabilities first</li>
            <li>Best when you are actively dating and messaging often</li>
            <li>Priority access to select beta improvements</li>
          </ul>
        </div>
      </div>

      <div
        className="surface"
        style={{
          padding: 20,
          borderRadius: "var(--r-lg)",
          border: "1px solid rgba(255,255,255,0.1)",
          marginBottom: 32,
        }}
      >
        <h2 className="h2" style={{ margin: "0 0 10px", fontSize: "1.05rem" }}>
          Subscriptions &amp; billing
        </h2>
        <p className="body muted" style={{ margin: 0, lineHeight: 1.6 }}>
          <strong style={{ color: "var(--text)" }}>Paid plans renew automatically every month</strong> until you cancel. You
          can cancel at any time; you typically keep access through the end of the current billing period. Payments are
          processed by our merchant of record (Paddle). Local taxes and currency may apply at checkout. See our{" "}
          <Link href="/terms" style={{ color: "var(--accent)" }}>
            Terms
          </Link>
          ,{" "}
          <Link href="/refunds" style={{ color: "var(--accent)" }}>
            Refund Policy
          </Link>
          , and{" "}
          <Link href="/privacy" style={{ color: "var(--accent)" }}>
            Privacy Policy
          </Link>{" "}
          for full details.
        </p>
      </div>

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 14,
          textAlign: "center",
          padding: "8px 0 12px",
        }}
      >
        <p className="body muted" style={{ margin: 0, maxWidth: "48ch", lineHeight: 1.55 }}>
          New here? Create a free account. Already signed in? Open the in-app paywall to choose Premium or Premium+.
        </p>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, justifyContent: "center" }}>
          <Link className="btn btn-primary" href="/signup">
            Start free
          </Link>
          <Link className="btn btn-secondary" href="/login?next=/paywall">
            Log in to upgrade
          </Link>
        </div>
        <Link href="/contact" className="body muted" style={{ fontSize: 14 }}>
          Questions? Contact us
        </Link>
      </div>
    </div>
  );
}
