"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { ApiError, apiGet, clearSession, hasSession } from "../src/api/client";
import { useDesktopSettings } from "../src/desktop/bridge";

function DesktopApiBootstrap() {
  // On every page, not just settings: the renderer must know the configured API
  // base URL before the first request leaves the app.
  useDesktopSettings();
  return null;
}

function AuthGate({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/";
  const router = useRouter();
  const isLoginRoute = pathname === "/login" || pathname === "/login/";
  const [ready, setReady] = useState(isLoginRoute);

  useEffect(() => {
    let cancelled = false;
    if (isLoginRoute) {
      setReady(true);
      return;
    }
    if (!hasSession()) {
      setReady(false);
      router.replace("/login/");
      return;
    }
    setReady(false);
    void apiGet<unknown>("/api/v1/me")
      .then(() => {
        if (!cancelled) setReady(true);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 401) {
          clearSession();
          router.replace("/login/");
          return;
        }
        // Offline or degraded control plane: keep the session and let the page
        // show its normal offline state instead of logging the user out.
        setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, [isLoginRoute, router]);

  if (!ready) {
    return (
      <div className="panel" style={{ margin: 24 }}>
        <p className="muted small">正在验证登录状态…</p>
      </div>
    );
  }
  return <>{children}</>;
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: 1,
            refetchOnWindowFocus: false,
            staleTime: 15_000,
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <DesktopApiBootstrap />
      <AuthGate>{children}</AuthGate>
    </QueryClientProvider>
  );
}
