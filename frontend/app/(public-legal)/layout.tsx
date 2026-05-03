import { PublicMarketingShell } from "../components/public/PublicMarketingShell";

export const dynamic = "force-static";

export default function PublicLegalLayout({ children }: { children: React.ReactNode }) {
  return <PublicMarketingShell>{children}</PublicMarketingShell>;
}
