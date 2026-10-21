import type { ApiPath, paths } from "./types.gen";

/** Mirrors the backend error envelope: { error: { code, message, details? } }. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly retryAfterSeconds: number | null;
  constructor(status: number, code: string, details: Record<string, unknown> = {}, retryAfterSeconds: number | null = null) {
    super(code);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.retryAfterSeconds = retryAfterSeconds;
  }
  /** Human-readable, localised message — never a bare English enum. */
  get message(): string {
    const mapped = ERROR_MESSAGES[this.code];
    if (mapped) return mapped;
    const raw = typeof this.details.message === "string" ? this.details.message : null;
    return raw ?? `请求失败（${this.status} ${this.code}）`;
  }
}

/** Stable error-code → Chinese copy table. Unknown codes fall back to the envelope message. */
export const ERROR_MESSAGES: Record<string, string> = {
  repo_url_not_allowed: "只接受 github.com 公开仓库地址（https://github.com/owner/repo）。",
  repo_not_found: "仓库不存在或不可访问，请确认地址与可见性。",
  repo_too_large: "仓库超过当前部署的大小上限。",
  project_exists: "项目已存在，直接新建任务或查看历史即可。",
  quota_exceeded: "配额已用尽，请稍后重试。",
  rate_limited: "请求过于频繁，请按倒计时后重试。",
  login_rate_limited: "登录尝试过多，请稍后再试。",
  invalid_credentials: "邮箱或密码不正确。",
  email_in_use: "该邮箱已经注册。",
  invalid_refresh_token: "登录已失效，请重新登录。",
  refresh_reuse_detected: "登录会话已失效，请重新登录。",
  llm_settings_invalid: "模型配置不完整，请检查提供方、模型和密钥。",
  maintenance: "控制面暂停接单，请稍后再试。",
  forbidden: "当前账号没有访问该资源的权限。",
  unauthorized: "登录状态已失效，请重新登录。",
  not_found: "资源不存在或已被删除。",
  validation_error: "提交内容未通过校验。",
  internal: "服务内部错误，请携带请求 ID 反馈。",
};

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  /** Query string values; undefined entries are dropped. */
  query?: Record<string, string | number | boolean | undefined | null>;
  body?: unknown;
  signal?: AbortSignal;
  headers?: Record<string, string>;
  /** Bearer access token kept in memory only (never persisted by the web app). */
  token?: string | null;
  /** API key channel (X-Revive-Key) used by the CLI/CI and the desktop settings page. */
  apiKey?: string | null;
  /** Login/refresh must not trigger the automatic refresh-retry loop. */
  skipRefresh?: boolean;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type?: string;
  expires_in?: number;
}

const DEFAULT_BASE_URL = "/";
const ACCESS_TOKEN_KEY = "revive.access_token";
const REFRESH_TOKEN_KEY = "revive.refresh_token";
let baseUrlOverride: string | null = null;

function storageGet(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function storageSet(key: string, value: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (value === null || value.length === 0) window.sessionStorage.removeItem(key);
    else window.sessionStorage.setItem(key, value);
  } catch {
    /* private mode: the in-memory copy still works for this page */
  }
}

let accessToken: string | null = storageGet(ACCESS_TOKEN_KEY);
let refreshToken: string | null = storageGet(REFRESH_TOKEN_KEY);

export function setSession(access: string, refresh: string): void {
  accessToken = access.length > 0 ? access : null;
  refreshToken = refresh.length > 0 ? refresh : null;
  storageSet(ACCESS_TOKEN_KEY, accessToken);
  storageSet(REFRESH_TOKEN_KEY, refreshToken);
  notifySession();
}

export function clearSession(): void {
  accessToken = null;
  refreshToken = null;
  storageSet(ACCESS_TOKEN_KEY, null);
  storageSet(REFRESH_TOKEN_KEY, null);
  notifySession();
}

function notifySession(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event("revive-session"));
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function getRefreshToken(): string | null {
  return refreshToken;
}

export function hasSession(): boolean {
  return Boolean(accessToken || refreshToken);
}

export function apiBaseUrl(): string {
  const fromEnv = process.env.NEXT_PUBLIC_REVIVE_API_URL;
  const value = baseUrlOverride ?? (fromEnv && fromEnv.length > 0 ? fromEnv : DEFAULT_BASE_URL);
  return value === "/" ? "" : trimSlash(value);
}

/**
 * Desktop only: the Electron main process injects the persisted API base URL
 * through window.reviveDesktop before the bundle boots.
 */
export function setApiBaseUrl(url: string | null): void {
  baseUrlOverride = url && url.trim().length > 0 ? trimSlash(url.trim()) : null;
}

function trimSlash(value: string): string {
  return value.endsWith("/") ? value.slice(0, -1) : value;
}

function buildQuery(query: RequestOptions["query"]): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs.length > 0 ? `?${qs}` : "";
}

/** Absolute URL for an API path (also used for SSE endpoints). */
export function apiUrl(path: string, query?: RequestOptions["query"]): string {
  const absolute = /^https?:\/\//.test(path)
    ? path
    : `${apiBaseUrl()}${path.startsWith("/") ? path : `/${path}`}`;
  return `${absolute}${buildQuery(query)}`;
}

let refreshPromise: Promise<boolean> | null = null;

/** Rotate the refresh token and keep the in-memory/session copy in sync. */
export async function refreshAccessToken(): Promise<boolean> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = refreshOnce().finally(() => {
    refreshPromise = null;
  });
  return refreshPromise;
}

async function refreshOnce(): Promise<boolean> {
  if (!refreshToken) return false;
  try {
    const response = await fetch(apiUrl("/api/v1/auth/refresh"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!response.ok) {
      clearSession();
      return false;
    }
    const pair = (await response.json()) as TokenPair;
    if (!pair.access_token || !pair.refresh_token) {
      clearSession();
      return false;
    }
    setSession(pair.access_token, pair.refresh_token);
    return true;
  } catch {
    return false;
  }
}

/**
 * Thin fetch wrapper. Business code must never call fetch() with a raw
 * "/api/v1/..." string; it goes through here (T-FE-02).
 */
export async function request<T>(path: ApiPath | string, options: RequestOptions = {}): Promise<T> {
  const url = apiUrl(path, options.query);

  const send = async (): Promise<Response> => {
    const token = options.token ?? accessToken;
    const headers: Record<string, string> = {
      Accept: "application/json",
      ...(options.headers ?? {}),
    };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (token) headers.Authorization = `Bearer ${token}`;
    if (options.apiKey) headers["X-Revive-Key"] = options.apiKey;
    try {
      return await fetch(url, {
        method: options.method ?? "GET",
        credentials: "include",
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: options.signal,
      });
    } catch (cause) {
      throw new ApiError(0, "network_unreachable", { cause: String(cause), url });
    }
  };

  let response = await send();
  if (
    response.status === 401 &&
    !options.skipRefresh &&
    !options.apiKey &&
    !options.token &&
    refreshToken &&
    (await refreshAccessToken())
  ) {
    response = await send();
  }

  if (!response.ok) {
    let parsed: unknown = null;
    try {
      parsed = await response.json();
    } catch {
      parsed = null;
    }
    const envelope = pickEnvelope(parsed);
    const retryAfter = parseRetryAfter(response.headers.get("Retry-After"));
    throw new ApiError(response.status, envelope.code, envelope.details, retryAfter);
  }

  if (response.status === 204) return undefined as T;
  const text = await response.text();
  if (text.length === 0) return undefined as T;
  return JSON.parse(text) as T;
}

function pickEnvelope(parsed: unknown): { code: string; details: Record<string, unknown> } {
  if (typeof parsed !== "object" || parsed === null) return { code: "internal", details: {} };
  const root = parsed as Record<string, unknown>;
  const error = typeof root.error === "object" && root.error !== null ? (root.error as Record<string, unknown>) : null;
  if (error) {
    const code = typeof error.code === "string" ? error.code : "internal";
    const details: Record<string, unknown> = { ...error };
    if (typeof error.message === "string") details.message = error.message;
    if (typeof error.request_id === "string") details.request_id = error.request_id;
    return { code, details };
  }
  // FastAPI HTTPException default shape: { detail: ... }
  const detail = root.detail;
  if (typeof detail === "string") return { code: detail, details: root };
  if (typeof detail === "object" && detail !== null) {
    const d = detail as Record<string, unknown>;
    return { code: typeof d.code === "string" ? d.code : "validation_error", details: d };
  }
  return { code: "internal", details: root };
}

function parseRetryAfter(header: string | null): number | null {
  if (!header) return null;
  const seconds = Number.parseInt(header, 10);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

export const apiGet = <T>(path: ApiPath | string, options: RequestOptions = {}) => request<T>(path, { ...options, method: "GET" });
export const apiPost = <T>(path: ApiPath | string, body?: unknown, options: RequestOptions = {}) => request<T>(path, { ...options, method: "POST", body });
export const apiDelete = <T>(path: ApiPath | string, options: RequestOptions = {}) => request<T>(path, { ...options, method: "DELETE" });

/** Type-level guard that keeps raw strings honest against the generated path map. */
export type KnownPath = keyof paths;
