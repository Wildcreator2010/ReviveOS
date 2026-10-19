import { app, screen, type BrowserWindow, type Rectangle } from "electron";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

export interface StoredWindowState extends Rectangle {
  maximized: boolean;
}

const DEFAULT_STATE: StoredWindowState = { x: 0, y: 0, width: 1360, height: 880, maximized: false };

/** Remembers window position/size/maximized across launches. */
export class WindowStateStore {
  private readonly file: string;

  constructor() {
    this.file = join(app.getPath("userData"), "revive-window-state.json");
  }

  load(): StoredWindowState {
    let state: StoredWindowState = { ...DEFAULT_STATE };
    try {
      if (existsSync(this.file)) {
        const parsed = JSON.parse(readFileSync(this.file, "utf8")) as Partial<StoredWindowState>;
        state = {
          x: typeof parsed.x === "number" ? parsed.x : DEFAULT_STATE.x,
          y: typeof parsed.y === "number" ? parsed.y : DEFAULT_STATE.y,
          width: typeof parsed.width === "number" ? parsed.width : DEFAULT_STATE.width,
          height: typeof parsed.height === "number" ? parsed.height : DEFAULT_STATE.height,
          maximized: parsed.maximized === true,
        };
      }
    } catch {
      state = { ...DEFAULT_STATE };
    }
    return this.ensureVisible(state);
  }

  /** Drops off-screen coordinates (e.g. a monitor was disconnected). */
  private ensureVisible(state: StoredWindowState): StoredWindowState {
    const displays = screen.getAllDisplays();
    const visible = displays.some((display) => {
      const area = display.workArea;
      return state.x < area.x + area.width && state.x + state.width > area.x && state.y < area.y + area.height && state.y + state.height > area.y;
    });
    if (visible) return state;
    const primary = screen.getPrimaryDisplay().workArea;
    return { ...state, x: primary.x + 40, y: primary.y + 40, width: Math.min(state.width, primary.width), height: Math.min(state.height, primary.height) };
  }

  track(window: BrowserWindow): void {
    const persist = () => {
      if (window.isDestroyed()) return;
      const bounds = window.getNormalBounds();
      this.save({ ...bounds, maximized: window.isMaximized() });
    };
    let timer: NodeJS.Timeout | null = null;
    const debounced = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(persist, 400);
    };
    window.on("resize", debounced);
    window.on("move", debounced);
    window.on("maximize", debounced);
    window.on("unmaximize", debounced);
    window.on("close", () => {
      if (timer) clearTimeout(timer);
      persist();
    });
  }

  private save(state: StoredWindowState): void {
    try {
      mkdirSync(dirname(this.file), { recursive: true });
      writeFileSync(this.file, JSON.stringify(state, null, 2), "utf8");
    } catch (error) {
      console.error("[window-state] persist failed:", error);
    }
  }
}
