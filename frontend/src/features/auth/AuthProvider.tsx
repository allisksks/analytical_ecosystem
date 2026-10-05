import { useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { API_BASE, api, tokenStore } from "../../shared/api/client";
import type { Me } from "../../shared/api/types";

type Status = "loading" | "anonymous" | "authenticated";

export interface MfaChallenge {
  token: string;
  setupRequired: boolean;
}

interface AuthValue {
  status: Status;
  me: Me | null;
  login: (email: string, password: string) => Promise<MfaChallenge | null>;
  verifyMfa: (mfaToken: string, code: string) => Promise<void>;
  logout: () => Promise<void>;
  reload: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [me, setMe] = useState<Me | null>(null);
  const qc = useQueryClient();

  const loadMe = useCallback(async () => {
    const { data } = await api.GET("/api/v1/auth/me");
    setMe(data ?? null);
    setStatus(data ? "authenticated" : "anonymous");
  }, []);

  const reset = useCallback(() => {
    tokenStore.set(null);
    setMe(null);
    setStatus("anonymous");
    qc.clear();
  }, [qc]);

  useEffect(() => {
    tokenStore.onUnauthorized(reset);
    // silent sign-in from the refresh cookie
    fetch(`${API_BASE}/auth/refresh`, { method: "POST", credentials: "include" })
      .then(async (r) => {
        if (!r.ok) return reset();
        tokenStore.set(((await r.json()) as { access_token: string }).access_token);
        await loadMe();
      })
      .catch(reset);
  }, [loadMe, reset]);

  const login = useCallback(
    async (email: string, password: string) => {
      const { data } = await api.POST("/api/v1/auth/login", { body: { email, password } });
      if (!data) return null;
      if (data.mfa_required && data.mfa_token) {
        return { token: data.mfa_token, setupRequired: Boolean(data.mfa_setup_required) };
      }
      tokenStore.set(data.access_token ?? null);
      await loadMe();
      return null;
    },
    [loadMe],
  );

  const verifyMfa = useCallback(
    async (mfaToken: string, code: string) => {
      const { data } = await api.POST("/api/v1/auth/mfa/verify", { body: { mfa_token: mfaToken, code } });
      tokenStore.set(data?.access_token ?? null);
      await loadMe();
    },
    [loadMe],
  );

  const logout = useCallback(async () => {
    try {
      await api.POST("/api/v1/auth/logout");
    } finally {
      reset();
    }
  }, [reset]);

  const value = useMemo(
    () => ({ status, me, login, verifyMfa, logout, reload: loadMe }),
    [status, me, login, verifyMfa, logout, loadMe],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/** UI-only permission check (the backend enforces the real policy). */
// eslint-disable-next-line react-refresh/only-export-components
export function useCan() {
  const { me } = useAuth();
  return useCallback(
    (permission: string, projectId?: string | null) => {
      if (!me) return false;
      if (projectId) return (me.project_permissions[projectId] ?? []).includes(permission);
      return (
        me.org_permissions.includes(permission) ||
        Object.values(me.project_permissions).some((perms) => perms.includes(permission))
      );
    },
    [me],
  );
}
