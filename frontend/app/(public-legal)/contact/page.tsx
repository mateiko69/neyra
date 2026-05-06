import type { Metadata } from "next";
import Link from "next/link";

export const dynamic = "force-static";

export const metadata: Metadata = {
  title: "Contact — NEYRA",
  description: "Reach NEYRA support and business teams.",
};

export default function ContactPage() {
  return (
    <article className="legal-prose">
      <h1>Contact</h1>
      <p className="legal-effective">Operator: NEYRA</p>

      <h2>Customer support</h2>
      <p>
        Email{" "}
        <a href="mailto:support@neyra.app">
          <strong>support@neyra.app</strong>
        </a>{" "}
        for account help, billing questions, safety reports, and privacy or data requests.
      </p>
      <p>
        We aim to respond to most messages within <strong>two business days</strong>. Complex cases (for example legal or
        safety investigations) may take longer.
      </p>

      <h2>Business inquiries</h2>
      <p>
        Email{" "}
        <a href="mailto:hello@neyra.app">
          <strong>hello@neyra.app</strong>
        </a>{" "}
        for partnerships, press, and commercial questions.
      </p>

      <h2>Legal &amp; policies</h2>
      <p className="legal-prose-lead">Official documents:</p>
      <ul>
        <li>
          <Link href="/privacy">Privacy Policy</Link>
        </li>
        <li>
          <Link href="/terms">Terms of Service</Link>
        </li>
        <li>
          <Link href="/refunds">Refund Policy</Link>
        </li>
      </ul>

      <h2>Premium plans</h2>
      <p>
        Compare options on the <Link href="/premium">Pricing</Link> page.
      </p>
    </article>
  );
}
