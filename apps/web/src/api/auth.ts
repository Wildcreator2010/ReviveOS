"use client";

import {
  clearSession,
  getRefreshToken,
  notifyIdentityChanged,
  request,
  setSession,
  type TokenPair,
} from "./client";

export async function login(email: string, password: string): Promise<void> {
  const pair = await request<TokenPair>("/api/v1/auth/login", {
    method: "POST",
    body: { email, password },
    skipRefresh: true,
  });
  setSession(pair.access_token, pair.refresh_token);
  notifyIdentityChanged();
}

export async function register(email: string, password: string): Promise<void> {
  const pair = await request<TokenPair>("/api/v1/auth/register", {
    method: "POST",
    body: { email, password },
    skipRefresh: true,
  });
  setSession(pair.access_token, pair.refresh_token);
  notifyIdentityChanged();
}

export async function logout(): Promise<void> {
  const refresh = getRefreshToken();
  // Clear locally first so a slow/offline control plane cannot keep the UI logged in.
  clearSession();
  if (!refresh) return;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 3000);
  try {
    await request<void>("/api/v1/auth/logout", {
      method: "POST",
      body: { refresh_token: refresh },
      skipRefresh: true,
      signal: controller.signal,
    });
  } catch {
    /* revocation is best effort; the local session is already gone */
  } finally {
    clearTimeout(timer);
  }
}
