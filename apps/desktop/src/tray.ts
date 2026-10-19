import { app, Menu, Tray, nativeImage, shell, type BrowserWindow } from "electron";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { DEFAULT_API_BASE_URL } from "./channels";

const TRAY_PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAjUlEQVR42mNgGAWjYBSMglEwCkbBKBgFo2AUjIJRMApGwSgYBaNgFIyCUTAKRsEoGAWjYBSMglEwCkbBKBgFo2AUjIJRMApGwSgYBaNgFIyCUTAKRsEoGAWjYBSMglEwCkbBKBgFo2AUjIJRMApGwSgYBaNgFIyCUTAKRsEoGAWjYBSMglEwCkbBKBgFAwEAc0QAAdfQjRsAAAAASUVORK5CYII=";

export interface TrayOptions {
  window: BrowserWindow;
  apiBaseUrl: string;
  onQuit: () => void;
}

/** System tray: show/hide, open the control-plane URL, quit. Falls back silently when unsupported. */
export function createTray({ window, apiBaseUrl, onQuit }: TrayOptions): Tray | null {
  const iconPath = join(app.getAppPath(), "icon.png");
  let image = existsSync(iconPath) ? nativeImage.createFromPath(iconPath) : nativeImage.createEmpty();
  if (image.isEmpty()) {
    image = nativeImage.createFromDataURL(`data:image/png;base64,${TRAY_PNG_BASE64}`);
  }
  let tray: Tray;
  try {
    tray = new Tray(image);
  } catch (error) {
    console.error("[tray] unavailable:", error);
    return null;
  }
  const menu = Menu.buildFromTemplate([
    {
      label: "显示 ReviveOS ICU",
      click: () => {
        if (window.isMinimized()) window.restore();
        window.show();
        window.focus();
      },
    },
    { type: "separator" },
    {
      label: `控制面：${apiBaseUrl || DEFAULT_API_BASE_URL}`,
      click: () => void shell.openExternal(apiBaseUrl || DEFAULT_API_BASE_URL),
    },
    { type: "separator" },
    { label: "退出", click: onQuit },
  ]);
  tray.setToolTip("ReviveOS ICU");
  tray.setContextMenu(menu);
  tray.on("click", () => {
    if (window.isVisible()) window.hide();
    else window.show();
  });
  return tray;
}
