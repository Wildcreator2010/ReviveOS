"use client";

import { useEffect, useState } from "react";
import { apiBaseUrl, setApiBaseUrl } from "../api/client";

/**
 * Desktop bridge exposed by apps/desktop/src/preload.ts over contextBridge.
 * The web bundle must work in a plain browser too, so every use is guarded.
 */
export interface ReviveDesktopBridge {
  platform: string;
  version: string;
  getSettings(): Promise<{ apiBaseUrl: string | null; backendStatus?: string }>;
  setApiBaseUrl(url: string): Promise<{ apiBaseUrl: string | null }>;
  notify(payload: { title: string; body: string }): Promise<void>;
  onBackendStatus(listener: (status: string) => void): () => void;
}

declare global {
  interface Window {
    reviveDesktop?: ReviveDesktopBridge;
  }
}

export function desktopBridge(): ReviveDesktopBridge | null {
  if (typeof window === "undefined") return null;
  return window.reviveDesktop ?? null;
}

export interface DesktopSettingsState {
  available: boolean;
  version: string | null;
  apiBaseUrl: string | null;
  backendStatus: string | null;
  setApiBaseUrl: (url: string) => Promise<void>;
}

/** Loads persisted desktop settings once and mirrors the API base URL into the fetch client. */
export function useDesktopSettings(): DesktopSettingsState {
  const [state, setState] = useState<{ version: string | null; apiBaseUrl: string | null; backendStatus: string | null }>({
    version: null,
    apiBaseUrl: null,
    backendStatus: null,
  });
  const bridge = desktopBridge();

  useEffect(() => {
    if (!bridge) {
      // Browser fallback: honour a previously saved local override.
      try {
        const stored = window.localStorage.getItem("revive.apiBaseUrl");
        if (stored) setApiBaseUrl(stored);
      } catch {
        /* ignore */
      }
      return;
    }
    let cancelled = false;
    void bridge
      .getSettings()
      .then((settings) => {
        if (cancelled) return;
        if (settings.apiBaseUrl) setApiBaseUrl(settings.apiBaseUrl);
        setState({ version: bridge.version, apiBaseUrl: settings.apiBaseUrl, backendStatus: settings.backendStatus ?? null });
      })
      .catch(() => {
        /* bridge unavailable: keep defaults */
      });
    const dispose = bridge.onBackendStatus((status) => setState((current) => ({ ...current, backendStatus: status })));
    return () => {
      cancelled = true;
      dispose();
    };
  }, [bridge]);

  return {
    available: bridge !== null,
    version: state.version,
    apiBaseUrl: state.apiBaseUrl ?? (bridge ? null : typeof window === "undefined" ? null : window.localStorage.getItem("revive.apiBaseUrl")) ?? apiBaseUrl(),
    backendStatus: state.backendStatus,
    setApiBaseUrl: async (url: string) => {
      setApiBaseUrl(url);
      if (bridge) await bridge.setApiBaseUrl(url);
      setState((current) => ({ ...current, apiBaseUrl: url }));
    },
  };
}
