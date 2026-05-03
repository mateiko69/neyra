import type { Metadata } from "next";

export const dynamic = "force-static";

export const metadata: Metadata = {
  title: "Privacy Policy — NEYRA",
  description: "How NEYRA collects, uses, and protects personal information.",
};

export default function PrivacyPage() {
  return (
    <article className="legal-prose">
      <h1>Privacy Policy</h1>
      <p className="legal-effective">
        Effective date: May 3, 2026 · Operator: <strong>NEYRA</strong> (&quot;we,&quot; &quot;us,&quot; or &quot;our&quot;)
      </p>

      <h2>1. Introduction</h2>
      <p>
        This Privacy Policy explains how NEYRA handles personal information when you use our websites, mobile
        experiences, and related services (together, the &quot;Service&quot;). We are committed to describing our
        practices in plain language. If you have questions, contact us at{" "}
        <a href="mailto:support@neyra.app">support@neyra.app</a>.
      </p>

      <h2>2. Information we collect</h2>
      <p>Depending on how you use the Service, we may collect:</p>
      <ul>
        <li>
          <strong>Account and profile data:</strong> such as email address, age or date-of-birth where required,
          display name, gender or orientation preferences you choose to provide, photos or media you upload, bio text,
          and verification-related signals when you participate in verification flows.
        </li>
        <li>
          <strong>Activity and usage data:</strong> such as approximate location derived from IP or device settings
          (where permitted), interactions with profiles or chat messages you send through the Service, feature usage,
          diagnostics, and security logs.
        </li>
        <li>
          <strong>Device and technical data:</strong> such as device type, operating system, app version, language,
          and identifiers needed to operate sessions and prevent abuse.
        </li>
        <li>
          <strong>Payment-related data:</strong> when you purchase a subscription, our payment provider (Paddle, as
          merchant of record) processes payment details. We typically receive limited billing metadata (for example,
          subscription status, transaction references, and partial identifiers) rather than your full card number.
        </li>
        <li>
          <strong>Communications you send us:</strong> such as support emails to{" "}
          <a href="mailto:support@neyra.app">support@neyra.app</a> or business inquiries to{" "}
          <a href="mailto:hello@neyra.app">hello@neyra.app</a>.
        </li>
      </ul>

      <h2>3. How we use information</h2>
      <p>We use information to:</p>
      <ul>
        <li>Provide, personalize, and improve the Service, including AI-assisted features you explicitly interact with.</li>
        <li>Maintain safety and integrity, including moderation, spam prevention, fraud detection, and enforcing our Terms.</li>
        <li>Process subscriptions and communicate transactional notices such as receipts or subscription changes.</li>
        <li>Respond to lawful requests and protect rights, safety, and security.</li>
        <li>Analyze aggregated or de-identified usage to improve product quality (where permitted).</li>
      </ul>

      <h2>4. AI features</h2>
      <p>
        When you use AI-assisted tools within NEYRA, portions of your prompts, chat context, or profile signals may be
        processed by automated systems to generate suggestions. You choose what you send to other users. Do not share
        sensitive health, financial, or government identifier information in chats unless you accept the risk of doing
        so.
      </p>

      <h2>5. Legal bases (EEA/UK/Switzerland users)</h2>
      <p>
        Where GDPR-style laws apply, we rely on appropriate bases such as performance of a contract, legitimate
        interests (for example securing the Service and improving features), consent where required, and compliance with
        legal obligations.
      </p>

      <h2>6. Sharing of information</h2>
      <p>We may share information with:</p>
      <ul>
        <li>
          <strong>Service providers</strong> who process data on our instructions (for example hosting, analytics,
          customer support tooling, email delivery, security vendors, and AI inference providers).
        </li>
        <li>
          <strong>Payment processors:</strong> Paddle (or successor merchant of record) to bill subscriptions and
          handle taxes and invoices where applicable.
        </li>
        <li>
          <strong>Authorities:</strong> when required by law or to protect safety.
        </li>
        <li>
          <strong>Corporate transactions:</strong> such as a merger or acquisition, subject to safeguards.
        </li>
      </ul>
      <p>We do not sell your personal information as traditionally defined in applicable &quot;Do Not Sell&quot; laws.</p>

      <h2>7. Retention</h2>
      <p>
        We retain information as long as needed to provide the Service, comply with law, resolve disputes, and enforce
        agreements. Some logs may be retained for a shorter or longer period based on security needs. When retention
        ends, we delete or de-identify information where feasible.
      </p>

      <h2>8. Security</h2>
      <p>
        We use administrative, technical, and organizational measures designed to protect information. No online service
        can guarantee absolute security.
      </p>

      <h2>9. International transfers</h2>
      <p>
        We may process information in countries other than where you live. Where required, we implement appropriate
        safeguards such as standard contractual clauses.
      </p>

      <h2>10. Your choices and rights</h2>
      <p>Depending on your region, you may have rights to access, correct, delete, export, or restrict certain processing.</p>
      <p>
        To submit a privacy request (including data deletion or access), email{" "}
        <a href="mailto:support@neyra.app">support@neyra.app</a> from the email associated with your account and describe
        your request. We may verify your identity before fulfilling it.
      </p>

      <h2>11. Children</h2>
      <p>
        The Service is not intended for children under the age required by applicable law to provide meaningful
        consent for dating services (often 18). If you believe a minor has provided information, contact us and we will
        take appropriate steps.
      </p>

      <h2>12. Third-party links</h2>
      <p>
        The Service may contain links to third parties. Their practices are governed by their own policies. Review
        Paddle&apos;s documentation for payment-related processing details.
      </p>

      <h2>13. Changes to this policy</h2>
      <p>
        We may update this Privacy Policy from time to time. We will post the revised version with a new effective
        date and, where appropriate, provide additional notice (such as an in-app message or email).
      </p>

      <h2>14. Contact</h2>
      <p>
        NEYRA — Privacy inquiries: <a href="mailto:support@neyra.app">support@neyra.app</a>
        <br />
        Business inquiries: <a href="mailto:hello@neyra.app">hello@neyra.app</a>
      </p>
    </article>
  );
}
