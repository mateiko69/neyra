"use client";

import Link from "next/link";
import type { ReactNode } from "react";

function NavPipe() {
  return (
    <li className="public-marketing-pipe" aria-hidden="true">
      <span>|</span>
    </li>
  );
}

function FooterPipe() {
  return (
    <li className="public-marketing-footer-pipe" aria-hidden="true">
      <span>|</span>
    </li>
  );
}

export function PublicMarketingShell({ children }: { children: ReactNode }) {
  return (
    <div className="public-marketing-root">
      <a href="#public-main-content" className="public-marketing-skip">
        Skip to content
      </a>

      <header className="public-marketing-top">
        <div className="public-marketing-top-inner">
          <Link href="/" className="public-marketing-brand">
            NEYRA
          </Link>

          <nav className="public-marketing-nav" aria-label="Marketing">
            <ul className="public-marketing-nav-list">
              <li>
                <Link href="/premium" className="public-marketing-nav-link">
                  Premium
                </Link>
              </li>
              <NavPipe />
              <li>
                <Link href="/contact" className="public-marketing-nav-link">
                  Contact
                </Link>
              </li>
              <NavPipe />
              <li>
                <Link href="/login" className="public-marketing-nav-link public-marketing-nav-link--muted">
                  Log in
                </Link>
              </li>
              <NavPipe />
              <li className="public-marketing-nav-cta">
                <Link href="/signup" className="btn btn-primary public-marketing-signup">
                  Sign up
                </Link>
              </li>
            </ul>
          </nav>
        </div>
      </header>

      <main id="public-main-content" className="public-marketing-main">
        <div className="public-marketing-inner">{children}</div>
      </main>

      <footer className="public-marketing-footer">
        <div className="public-marketing-footer-inner">
          <div className="public-marketing-footer-brand">
            <span className="public-marketing-footer-name">NEYRA</span>
            <p className="public-marketing-footer-tag">
              AI-assisted dating tools — premium experiences optional.
            </p>
          </div>

          <nav aria-label="Legal">
            <ul className="public-marketing-footer-links">
              <li>
                <Link href="/privacy">Privacy Policy</Link>
              </li>
              <FooterPipe />
              <li>
                <Link href="/terms">Terms of Service</Link>
              </li>
              <FooterPipe />
              <li>
                <Link href="/refund">Refund Policy</Link>
              </li>
              <FooterPipe />
              <li>
                <Link href="/contact">Contact</Link>
              </li>
            </ul>
          </nav>

          <p className="public-marketing-footer-copy">© {new Date().getFullYear()} NEYRA. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
}
