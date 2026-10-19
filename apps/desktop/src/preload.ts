import { contextBridge, ipcRenderer } from "electron";
import { CHANNELS, type BackendStatus, type DesktopRuntime, type DesktopSettings, type NotifyPayload } from "./channels";

/**
 * The only surface the renderer gets: no ipcRenderer, no Node, no fs.
 * Every method maps to a validated main-process handler.
 */
const bridge = {
  platform: process.platform,
  version: process.env.REVIVE_DESKTOP_VERSION ?? "0.1.0",
  getSettings: (): Promise<DesktopSettings> => ipcRenderer.invoke(CHANNELS.getSettings),
  setApiBaseUrl: (url: string): Promise<DesktopSettings> => ipcRenderer.invoke(CHANNELS.setApiBaseUrl, url),
  getRuntime: (): Promise<DesktopRuntime> => ipcRenderer.invoke(CHANNELS.getRuntime),
  notify: (payload: NotifyPayload): Promise<boolean> => ipcRenderer.invoke(CHANNELS.notify, payload),
  onBackendStatus: (listener: (status: BackendStatus, detail: string | null) => void): (() => void) => {
    const handler = (_event: unknown, payload: { status: BackendStatus; detail: string | null }) => listener(payload.status, payload.detail);
    ipcRenderer.on(CHANNELS.backendStatus, handler);
    return () => ipcRenderer.removeListener(CHANNELS.backendStatus, handler);
  },
  onNavigate: (listener: (target: string) => void): (() => void) => {
    const handler = (_event: unknown, target: string) => listener(target);
    ipcRenderer.on(CHANNELS.windowState, handler);
    return () => ipcRenderer.removeListener(CHANNELS.windowState, handler);
  },
};

contextBridge.exposeInMainWorld("reviveDesktop", bridge);

export type ReviveDesktopPreloadBridge = typeof bridge;
