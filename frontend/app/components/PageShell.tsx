import type { ReactNode } from "react";

type PageShellProps = {
  children: ReactNode;
  className?: string;
};

/**
 * Shared vertical rhythm and section spacing for app pages.
 */
export function PageShell({ children, className = "" }: PageShellProps) {
  return <div className={`page-shell ${className}`.trim()}>{children}</div>;
}
