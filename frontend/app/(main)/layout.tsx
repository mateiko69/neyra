import { AppShell } from "../components/AppShell";
import { AuthBootstrapGate } from "../components/AuthBootstrapGate";
import { AuthRouteGuard } from "../components/AuthRouteGuard";
import { InitialRenderCompleteLog } from "../components/InitialRenderCompleteLog";
import { I18nProvider } from "../components/i18n/I18nProvider";

export default function MainAppLayout({ children }: { children: React.ReactNode }) {
  return (
    <I18nProvider>
      <InitialRenderCompleteLog />
      <AuthBootstrapGate>
        <AuthRouteGuard>
          <AppShell>{children}</AppShell>
        </AuthRouteGuard>
      </AuthBootstrapGate>
    </I18nProvider>
  );
}
