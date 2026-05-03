"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { getAuthBootstrapResult, invalidateAuthBootstrapCache } from "../../lib/auth/bootstrap";
import { applyAuthBootstrapResult } from "../../lib/api";

export type AuthBootPhase = "loading" | "ready" | "network";

export type AuthBootContextValue = {
  phase: AuthBootPhase;
  retry: () => void;
};

export const AuthBootContext = createContext<AuthBootContextValue | null>(null);

export function useAuthBoot(): AuthBootContextValue | null {
  return useContext(AuthBootContext);
}

/**
 * Runs GET /api/v1/auth/me once per app load (single-flight). Applies session to api auth state.
 * Network failure: retry UI, no redirect loop.
 */
export function AuthBootstrapGate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<AuthBootPhase>("loading");

  useEffect(() => {
    void getAuthBootstrapResult().then((r) => {
      applyAuthBootstrapResult(r);
      setPhase(r.status === "network" ? "network" : "ready");
    });
  }, []);

  const retry = useCallback(() => {
    invalidateAuthBootstrapCache();
    setPhase("loading");
    void getAuthBootstrapResult({ force: true }).then((r) => {
      applyAuthBootstrapResult(r);
      setPhase(r.status === "network" ? "network" : "ready");
    });
  }, []);

  const value = useMemo(() => ({ phase, retry }), [phase, retry]);

  return <AuthBootContext.Provider value={value}>{children}</AuthBootContext.Provider>;
}
