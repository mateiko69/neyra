import "./globals.css";
import "./public-marketing.css";
import { devLogMissingDemoAssets } from "../lib/demoPhotoServer";

devLogMissingDemoAssets();

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
