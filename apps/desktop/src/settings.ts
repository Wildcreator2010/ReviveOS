import { app } from "electron";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import type { DesktopSettings } from "./channels";

/**
 * Desktop settings live in Electron's userData directory (NOT in the asar):
 *   %APPDATA%\ReviveOS ICU\revive-desktop.json
 * The renderer can only change them through the validate-able IPC surface.
 */
const DEFAULTS: DesktopSettings = { apiBaseUrl: null };

export class SettingsStore {
  private readonly file: string;
  private cache: DesktopSettings;

  constructor() {
    this.file = join(app.getPath("userData"), "revive-desktop.json");
    this.cache = this.read();
  }

  get path(): string {
    return this.file;
  }

  all(): DesktopSettings {
    return { ...this.cache };
  }

  /** Validates and persists the control-plane base URL. Empty input resets to the default. */
  setApiBaseUrl(raw: string): DesktopSettings {
    const trimmed = raw.trim();
    if (trimmed.length === 0) {
      this.cache = { ...this.cache, apiBaseUrl: null };
      this.write();
      return this.all();
    }
    const parsed = new URL(trimmed);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      throw new Error("API 地址必须是 http(s) URL");
    }
    this.cache = { ...this.cache, apiBaseUrl: trimmed.replace(/\/+$/, "") };
    this.write();
    return this.all();
  }

  private read(): DesktopSettings {
    try {
      if (!existsSync(this.file)) return { ...DEFAULTS };
      const parsed = JSON.parse(readFileSync(this.file, "utf8")) as Partial<DesktopSettings>;
      const apiBaseUrl = typeof parsed.apiBaseUrl === "string" && parsed.apiBaseUrl.length > 0 ? parsed.apiBaseUrl : null;
      return { apiBaseUrl };
    } catch {
      return { ...DEFAULTS };
    }
  }

  private write(): void {
    try {
      mkdirSync(dirname(this.file), { recursive: true });
      writeFileSync(this.file, JSON.stringify(this.cache, null, 2), "utf8");
    } catch (error) {
      console.error("[settings] persist failed:", error);
    }
  }
}
