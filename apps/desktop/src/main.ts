import { app, BrowserWindow, Menu, Notification, dialog, ipcMain, shell } from "electron";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { BackendSupervisor } from "./backend";
import { CHANNELS, DEFAULT_API_BASE_URL, type DesktopRuntime, type NotifyPayload } from "./channels";
import { SettingsStore } from "./settings";
import { startStaticHost, type StaticHost } from "./staticServer";
import { createTray } from "./tray";
import { WindowStateStore } from "./windowState";

const isDev = !app.isPackaged;
const devWebUrl = process.env.REVIVE_WEB_URL ?? "http://127.0.0.1:3000";

let mainWindow: BrowserWindow | null = null;
let staticHost: StaticHost | null = null;
let webMode: DesktopRuntime["webMode"] = "bundled-static";
let webUrl = devWebUrl;
let settings: SettingsStore;
let windowState: WindowStateStore;
let backend: BackendSupervisor;
let quitting = false;

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });
  void bootstrap();
}

async function bootstrap(): Promise<void> {
  await app.whenReady();
  settings = new SettingsStore();
  windowState = new WindowStateStore();
  app.setAppUserModelId("dev.reviveos.icu");

  const apiBaseUrl = currentApiBaseUrl();
  backend = new BackendSupervisor({ apiBaseUrl, repoRoot: isDev ? resolve(app.getAppPath(), "..", "..") : null });
  backend.on("status", (status: string, detail: string | null) => {
    mainWindow?.webContents.send(CHANNELS.backendStatus, { status, detail });
  });
  void backend.start();

  webUrl = await resolveWebUrl();
  registerIpc();
  createWindow();
  createMenus();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
}

function currentApiBaseUrl(): string {
  return settings.all().apiBaseUrl ?? process.env.REVIVE_API_URL ?? DEFAULT_API_BASE_URL;
}

/**
 * Dev: load the running Next.js dev server (REVIVE_WEB_URL).
 * Production: serve the statically exported console from the asar over loopback.
 */
async function resolveWebUrl(): Promise<string> {
  if (isDev && process.env.REVIVE_WEB_URL) {
    webMode = "dev-server";
    return devWebUrl;
  }
  const exportDir = isDev ? resolve(app.getAppPath(), "web") : join(app.getAppPath(), "web");
  if (!existsSync(join(exportDir, "index.html"))) {
    throw new Error(`未找到打包的静态导出目录：${exportDir}（先运行 pnpm --filter web build）`);
  }
  staticHost = await startStaticHost(exportDir);
  webMode = "bundled-static";
  return staticHost.url;
}

function createWindow(): void {
  const state = windowState.load();
  const window = new BrowserWindow({
    x: state.x,
    y: state.y,
    width: state.width,
    height: state.height,
    minWidth: 960,
    minHeight: 640,
    backgroundColor: "#0a0f1c",
    show: false,
    autoHideMenuBar: true,
    title: "ReviveOS ICU",
    icon: join(app.getAppPath(), "icon.png"),
    webPreferences: {
      preload: join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: false,
    },
  });
  if (state.maximized) window.maximize();
  windowState.track(window);

  window.once("ready-to-show", () => window.show());
  window.on("closed", () => {
    mainWindow = null;
  });
  // Keep the app alive in the tray instead of exiting on the close button.
  window.on("close", (event) => {
    if (!quitting) {
      event.preventDefault();
      window.hide();
    }
  });
  window.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow = window;
  void window.loadURL(webUrl).catch((error) => {
    console.error("[main] failed to load console:", error);
    void dialog.showMessageBox({
      type: "error",
      title: "ReviveOS ICU",
      message: "无法加载控制台界面",
      detail: String(error),
    });
  });
  createTray({
    window,
    apiBaseUrl: currentApiBaseUrl(),
    onQuit: () => {
      quitting = true;
      app.quit();
    },
  });
}

function createMenus(): void {
  const template: Electron.MenuItemConstructorOptions[] = [
    {
      label: "文件",
      submenu: [
        { label: "刷新", accelerator: "CmdOrCtrl+R", click: () => mainWindow?.webContents.reload() },
        {
          label: "打开开发者工具",
          accelerator: "CmdOrCtrl+Shift+I",
          click: () => mainWindow?.webContents.openDevTools({ mode: "detach" }),
        },
        { type: "separator" },
        { label: "退出", accelerator: "CmdOrCtrl+Q", click: () => { quitting = true; app.quit(); } },
      ],
    },
    {
      label: "视图",
      submenu: [
        { label: "设置", click: () => mainWindow?.webContents.send(CHANNELS.windowState, "navigate-settings") },
        { label: `控制台地址：${webUrl}`, enabled: false },
        { label: `控制面：${currentApiBaseUrl()}`, enabled: false },
      ],
    },
    {
      label: "帮助",
      submenu: [
        { label: "关于", click: () => { void showAbout(); } },
        {
          label: "构建与配置文档",
          click: () => void shell.openExternal("https://github.com/reviveos/reviveos/blob/main/docs/desktop-app.md"),
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function showAbout(): Promise<void> {
  const runtime = buildRuntime();
  await dialog.showMessageBox({
    type: "info",
    title: "关于 ReviveOS ICU",
    message: `ReviveOS ICU ${runtime.version}`,
    detail: [
      `界面来源：${runtime.webMode === "dev-server" ? "开发服务器" : "打包静态导出"}`,
      `界面地址：${runtime.webUrl}`,
      `控制面：${currentApiBaseUrl()}（${runtime.backendStatus}）`,
      runtime.backendDetail ?? "",
    ]
      .filter((line) => line.length > 0)
      .join("\n"),
  });
}

function buildRuntime(): DesktopRuntime {
  const status = backend?.current ?? { status: "unknown" as const, detail: null };
  return {
    version: app.getVersion(),
    platform: process.platform,
    webMode,
    webUrl,
    backendStatus: status.status,
    backendDetail: status.detail,
  };
}

function registerIpc(): void {
  ipcMain.handle(CHANNELS.getSettings, () => settings.all());
  ipcMain.handle(CHANNELS.setApiBaseUrl, async (_event, url: unknown) => {
    if (typeof url !== "string") throw new Error("apiBaseUrl 必须是字符串");
    const next = settings.setApiBaseUrl(url);
    // Point the backend supervisor at the new endpoint without restarting the window.
    backend.stop();
    backend = new BackendSupervisor({ apiBaseUrl: currentApiBaseUrl(), repoRoot: isDev ? resolve(app.getAppPath(), "..", "..") : null });
    backend.on("status", (status: string, detail: string | null) => {
      mainWindow?.webContents.send(CHANNELS.backendStatus, { status, detail });
    });
    void backend.start();
    return next;
  });
  ipcMain.handle(CHANNELS.getRuntime, () => buildRuntime());
  ipcMain.handle(CHANNELS.notify, (_event, payload: unknown) => {
    if (typeof payload !== "object" || payload === null) return false;
    const { title, body } = payload as NotifyPayload;
    if (typeof title !== "string" || typeof body !== "string") return false;
    if (!Notification.isSupported()) return false;
    // Only ever called by the renderer after a real job-event arrived over SSE.
    new Notification({ title, body, icon: join(app.getAppPath(), "icon.png") }).show();
    return true;
  });
  ipcMain.handle(CHANNELS.windowState, () => ({ maximized: mainWindow?.isMaximized() ?? false, visible: mainWindow?.isVisible() ?? false }));
}

app.on("window-all-closed", () => {
  // Windows: keep running in the tray (window hides instead of closing).
  if (quitting) app.quit();
});
app.on("before-quit", () => {
  quitting = true;
  backend?.stop();
  void staticHost?.close();
});
