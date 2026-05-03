import type { Metadata } from "next";

export const dynamic = "force-static";

export const metadata: Metadata = {
  title: "Refund Policy — NEYRA",
  description: "Subscriptions, cancellation, and refunds for NEYRA paid plans.",
};

export default function RefundPage() {
  return (
    <article className="legal-prose">
      <h1>Refund Policy</h1>
      <p className="legal-effective">
        Effective date: May 3, 2026 · Operator: <strong>NEYRA</strong> (&quot;we,&quot; &quot;us,&quot; or &quot;our&quot;)
      </p>

      <h2>1. Overview</h2>
      <p>
        This Refund Policy explains how monthly subscriptions work for NEYRA Premium and Premium+ (together,
        &quot;paid plans&quot;), how cancellation affects billing, and when refunds may be available. Payments are
        processed by our merchant of record (for example, Paddle). Checkout screens may display additional terms that
        also apply.
      </p>

      <h2>2. Subscription nature</h2>
      <p>
        Paid plans are billed on a recurring basis (typically monthly) until cancelled. When you subscribe, you authorize
        recurring charges for each renewal period until you cancel.
      </p>

      <h2>3. Cancellation</h2>
      <p>
        You may cancel your subscription at any time using the cancellation path presented at purchase or in your
        account or billing portal. Canceling stops future renewals. Unless applicable law requires otherwise, you
        generally retain access to paid features until the end of the period you already paid for.
      </p>

      <h2>4. Refunds</h2>
      <ul>
        <li>
          <strong>General rule:</strong> Fees are generally non-refundable once a billing period has started, because
          the Service is delivered continuously during that period.
        </li>
        <li>
          <strong>Duplicate or erroneous charges:</strong> If you believe you were charged twice for the same period or
          charged in clear error, contact <a href="mailto:support@neyra.app">support@neyra.app</a> with transaction
          details; we or Paddle will investigate in good faith.
        </li>
        <li>
          <strong>Legal rights:</strong> Nothing in this policy limits mandatory consumer rights in your country (for
          example statutory withdrawal rights where they truly apply to digital services).
        </li>
        <li>
          <strong>Chargebacks:</strong> Please contact us before disputing charges with your bank so we can help. Abuse
          of chargebacks may lead to account closure.
        </li>
      </ul>

      <h2>5. Service issues</h2>
      <p>
        If paid features are unavailable for a prolonged period due to a substantial fault on our side, we may, at our
        discretion, extend access or offer a partial remedy consistent with the circumstances and applicable law.
      </p>

      <h2>6. Free trials and promotions</h2>
      <p>
        If we offer trials or promotional pricing, specific terms will be presented at signup. Unless stated otherwise,
        trial conversions bill according to the plan you select when the trial ends.
      </p>

      <h2>7. How to request help</h2>
      <p>
        Email <a href="mailto:support@neyra.app">support@neyra.app</a> from your account email and include:
      </p>
      <ul>
        <li>Your NEYRA account identifier or registered email</li>
        <li>Date and amount of charge (and Paddle receipt or reference if available)</li>
        <li>A brief description of the issue</li>
      </ul>

      <h2>8. Contact</h2>
      <p>
        NEYRA — Billing support: <a href="mailto:support@neyra.app">support@neyra.app</a>
        <br />
        Business inquiries: <a href="mailto:hello@neyra.app">hello@neyra.app</a>
      </p>
    </article>
  );
}
