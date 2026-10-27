import { createContext, useContext, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, post, setCsrf } from "./api";
import type { Me } from "./types";

interface AuthState {
  me: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<Me>;
  logout: () => Promise<void>;
  refresh: () => Promise<unknown>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        const me = await api<Me>("/auth/me");
        setCsrf(me.csrf_token);
        return me;
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
  });

  const value: AuthState = {
    me: q.data ?? null,
    loading: q.isLoading,
    login: async (email, password) => {
      const me = await post<Me>("/auth/login", { email, password });
      setCsrf(me.csrf_token);
      // Update the "me" entry in place so the observer above sees it; qc.clear() would orphan that observer
      // and leave the app thinking it's still signed out. Drop everything else cached for the previous user.
      qc.setQueryData(["me"], me);
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
      return me;
    },
    logout: async () => {
      await post("/auth/logout").catch(() => undefined);
      setCsrf("");
      qc.setQueryData(["me"], null);
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    },
    refresh: () => q.refetch(),
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

export const canManageAnything = (me: Me | null) => !!me && (me.is_superadmin || me.is_professor || me.is_dept_admin);
