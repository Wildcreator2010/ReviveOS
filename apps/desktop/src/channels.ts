/**
 * IPC channel names shared by the main process and the preload bridge.
 * Keep this file dependency-free so both bundles can import it.
 */
export const CHANNELS = {
  getSettings: "revive:settings:get",
  setApiBaseUrl: "revive:settings:set-api-base-url",
  getRuntime: "revive:runtime:get",
  notify: "revive:notify",
  backendStatus: "revive:backend:status",
  windowState: "revive:window:state",
} as const;

export type ChannelName = (typeof CHANNELS)[keyof typeof CHANNELS];

export interface DesktopSettings {
  /** Persisted control-plane base URL; null means "use the default local backend". */
  apiBaseUrl: string | null;
}

export interface DesktopRuntime {
  version: string;
  platform: string;
  /** Where the console is served from in this session. */
  webMode: "dev-server" | "bundled-static";
  webUrl: string;
  backendStatus: BackendStatus;
  backendDetail: string | null;
}

export type BackendStatus = "probing" | "external" | "spawning" | "failed" | "unknown";

export interface NotifyPayload {
  title: string;
  body: string;
}

export const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";
