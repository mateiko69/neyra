import type { Metadata } from "next";
import Link from "next/link";

export const dynamic = "force-static";

export const metadata: Metadata = {
  title: "Terms of Service — NEYRA",
  description: "Terms governing use of the NEYRA dating service and subscriptions.",
};

export default function TermsPage() {
  return (
    <article className="legal-prose">
      <h1>Terms of Service</h1>
      <p className="legal-effective">
        Effective date: May 3, 2026 · Operator: <strong>NEYRA</strong> (&quot;we,&quot; &quot;us,&quot; or &quot;our&quot;)
      </p>

      <h2>1. Agreement</h2>
      <p>
        These Terms of Service (&quot;Terms&quot;) govern your access to and use of NEYRA websites, applications, and
        related services (the &quot;Service&quot;). By creating an account, accessing, or using the Service, you agree
        to these Terms. If you do not agree, do not use the Service.
      </p>

      <h2>2. Eligibility</h2>
      <p>
        You must meet the minimum age required by the laws in your region to use a dating service (typically at least
        18). You represent that your registration information is accurate and that you have authority to enter these
        Terms.
      </p>

      <h2>3. The Service</h2>
      <p>
        NEYRA offers tools to meet people, communicate, and optionally use AI-assisted features to support conversation
        and planning. NEYRA does not guarantee any particular outcome (including matches, dates, or relationships).
        Dating involves independent choices by real people.
      </p>

      <h2>4. Accounts and security</h2>
      <p>
        You are responsible for safeguarding your credentials and for activity under your account. Notify us promptly
        at <a href="mailto:support@neyra.app">support@neyra.app</a> if you suspect unauthorized access.
      </p>

      <h2>5. Subscriptions and payments</h2>
      <ul>
        <li>
          NEYRA may offer paid plans such as Premium or Premium+ with recurring monthly billing unless otherwise stated
          at purchase.
        </li>
        <li>
          <strong>Renewal:</strong> Subscriptions renew automatically each billing period until you cancel in accordance
          with the cancellation steps presented at purchase or in your account tools.
        </li>
        <li>
          <strong>Merchant of record:</strong> Payments may be processed by Paddle (or another designated provider).
          Your checkout experience may include Paddle&apos;s terms and tax disclosures.
        </li>
        <li>
          <strong>Price changes:</strong> We may change pricing with reasonable notice where required by law; continued
          use after the effective date may constitute acceptance.
        </li>
      </ul>

      <h2>6. Cancellation</h2>
      <p>
        You may cancel your subscription using the mechanism provided at purchase or within account settings. Unless
        applicable law says otherwise, cancellation stops future renewals; you generally retain access through the end
        of the paid period. See the <Link href="/refunds">Refund Policy</Link> for additional detail.
      </p>

      <h2>7. Acceptable use and safety</h2>
      <p>You agree not to misuse the Service. Examples of prohibited conduct include:</p>
      <ul>
        <li>Harassment, hate, threats, or exploitation of minors.</li>
        <li>Impersonation, fraud, or deceptive dating schemes.</li>
        <li>Sharing illegal content or non-consensual intimate imagery.</li>
        <li>Attempting to scrape, overload, or compromise our systems or other users&apos; accounts.</li>
        <li>Circumventing moderation or verification controls.</li>
      </ul>
      <p>
        We may investigate reports, remove content, suspend or terminate accounts, and cooperate with authorities where
        appropriate. Some moderation may be automated; you may appeal reasonable outcomes via support.
      </p>

      <h2>8. User content</h2>
      <p>
        You retain rights to content you submit. You grant NEYRA a worldwide license to host, display, store,
        reproduce, and process your content as needed to operate, secure, and improve the Service, including training
        safeguards and AI features where permitted and consistent with our Privacy Policy.
      </p>

      <h2>9. Disclaimers</h2>
      <p>
        THE SERVICE IS PROVIDED &quot;AS IS&quot; AND &quot;AS AVAILABLE.&quot; TO THE MAXIMUM EXTENT PERMITTED BY LAW,
        WE DISCLAIM IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT. WE
        DO NOT WARRANT THAT THE SERVICE WILL BE UNINTERRUPTED OR ERROR-FREE.
      </p>

      <h2>10. Limitation of liability</h2>
      <p>
        TO THE MAXIMUM EXTENT PERMITTED BY LAW, NEYRA AND ITS SUPPLIERS WILL NOT BE LIABLE FOR INDIRECT, INCIDENTAL,
        SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, OR ANY LOSS OF PROFITS, DATA, OR GOODWILL. OUR AGGREGATE LIABILITY
        FOR CLAIMS RELATING TO THE SERVICE WILL NOT EXCEED THE GREATER OF (A) THE AMOUNTS YOU PAID TO NEYRA FOR THE
        SERVICE IN THE THREE MONTHS BEFORE THE EVENT GIVING RISE TO LIABILITY OR (B) ONE HUNDRED US DOLLARS (US $100),
        EXCEPT WHERE PROHIBITED BY LAW.
      </p>

      <h2>11. Indemnity</h2>
      <p>
        You will defend and indemnify NEYRA against claims arising from your misuse of the Service, your content, or
        your violation of these Terms, subject to applicable law.
      </p>

      <h2>12. Termination</h2>
      <p>
        We may suspend or terminate access if you violate these Terms or create risk. You may stop using the Service at
        any time. Provisions that by their nature should survive will survive termination.
      </p>

      <h2>13. Governing law and disputes</h2>
      <p>
        Unless mandatory consumer protections require otherwise, these Terms are governed by the laws applicable to the
        operator of NEYRA, without regard to conflict-of-law rules. Courts or arbitration in a designated venue may
        apply if specified in a future jurisdiction-specific addendum; until then, contact us to resolve issues
        informally.
      </p>

      <h2>14. Changes</h2>
      <p>
        We may modify these Terms. We will post updates with a new effective date and, where required, provide notice.
        Continued use after the effective date may constitute acceptance.
      </p>

      <h2>15. Contact</h2>
      <p>
        NEYRA — Support: <a href="mailto:support@neyra.app">support@neyra.app</a>
        <br />
        Business: <a href="mailto:hello@neyra.app">hello@neyra.app</a>
      </p>
    </article>
  );
}
