import type { Metadata } from "next";

export const dynamic = "force-static";

export const metadata: Metadata = {
  title: "Refund Policy | NEYRA",
  description:
    "NEYRA refund policy for subscriptions, trials, cancellations, unauthorized charges, and processing times.",
};

export default function RefundsPage() {
  return (
    <article className="legal-prose">
      <h1>Refund Policy</h1>
      <p className="legal-effective">
        Effective date: May 6, 2026 · Operator: <strong>NEYRA</strong> (&quot;we,&quot; &quot;us,&quot; or &quot;our&quot;)
      </p>

      <h2>Subscription billing</h2>
      <p>
        Paid plans (such as Premium and Premium+) are billed on a recurring basis until canceled. By subscribing, you
        authorize automatic renewal charges for each billing period. Payment processing may be handled by our merchant
        of record at checkout.
      </p>

      <h2>Trial policy</h2>
      <p>
        If a free trial or promotional period is offered, trial-specific terms are shown at signup. Unless explicitly
        stated otherwise, access automatically converts to a paid subscription when the trial ends.
      </p>

      <h2>Cancellation policy</h2>
      <p>
        You can cancel at any time from the billing flow provided at purchase or from available account billing tools.
        Cancellation stops future renewals, and you typically retain access through the end of the paid period.
      </p>

      <h2>Refund eligibility</h2>
      <ul>
        <li>
          <strong>General rule:</strong> Charges are generally non-refundable once a billing period begins because the
          service is delivered continuously during that period.
        </li>
        <li>
          <strong>Possible exceptions:</strong> Duplicate payments, clear processing errors, or situations required by
          applicable consumer law may be eligible for review.
        </li>
      </ul>

      <h2>Unauthorized charges</h2>
      <p>
        If you believe a charge was unauthorized, contact us immediately at{" "}
        <a href="mailto:support@getneyra.app">support@getneyra.app</a> and include the transaction date, amount, and
        receipt reference. We will investigate promptly with our payment processor.
      </p>

      <h2>Contact support</h2>
      <p>
        For billing and refund requests, email <a href="mailto:support@getneyra.app">support@getneyra.app</a> from the
        address associated with your account. Include a short description of the issue and any relevant receipt details
        so we can process your request faster.
      </p>

      <h2>Processing times</h2>
      <p>
        We aim to review most billing requests within 2 business days. If a refund is approved, the return to your
        original payment method usually appears within 5-10 business days, depending on your bank or card provider.
      </p>
    </article>
  );
}
