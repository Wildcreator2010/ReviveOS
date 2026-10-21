"use client";

import { clearSession, getRefreshToken, request, setSession, type TokenPair } from "./client";

export async function login(email: string, password: string): Promise<void> {
  const pair = await request<TokenPair>("/api/v1/auth/login", {
    method: "POST",
    body: { email, password },
    skipRefresh: true,
  });
  setSession(pair.access_token, pair.refresh_token);
}

export async function register(email: string, password: string): Promise<void> {
  const pair = await request<TokenPair>("/api/v1/auth/register", {
    method: "POST",
    body: { email, password },
    skipRefresh: true,
  });
  setSession(pair.access_token, pair.refresh_token);
}

export async function logout(): Promise<void> {
  const refresh = getRefreshToken();
  if (refresh) {
    try {
      await request<void>("/api/v1/auth/logout", {
        method: "POST",
        body: { refresh_token: refresh },
        skipRefresh: true,
      });
    } catch {
      /* local logout still takes effect when the control plane is offline */
    }
  }
  clearSession();
}
