import { spawn, type ChildProcess } from "node:child_process";
import { EventEmitter } from "node:events";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";
import type { BackendStatus } from "./channels";

export interface BackendSupervisorOptions {
  /** Control-plane base URL the console talks to. */
  apiBaseUrl: string;
  /** Repository root outside the package (dev only). */
  repoRoot: string | null;
  /** Extra env for the spawned process. */
  env?: NodeJS.ProcessEnv;
}

interface ProbeResult {
  reachable: boolean;
  detail: string;
}

/**
 * Connects the desktop app to a control plane.
 *
 * Order of operations:
 *  1. probe <apiBaseUrl> (GET /healthz);
 *  2. if unreachable AND the operator opted in with REVIVE_DESKTOP_SPAWN_BACKEND=1,
 *     spawn uvicorn from the workspace venv;
 *  3. otherwise report "failed" -- the console then shows its explicit offline state.
 *
 * The default is "connect, do not silently start anything": in a packaged install
 * there is no Python runtime, and pretending otherwise would hide the real reason
 * the ICU has no data.
 */
export class BackendSupervisor extends EventEmitter {
  private child: ChildProcess | null = null;
  private status: BackendStatus = "probing";
  private detail: string | null = null;
  private timer: NodeJS.Timeout | null = null;

  constructor(private readonly options: BackendSupervisorOptions) {
    super();
  }

  get current(): { status: BackendStatus; detail: string | null } {
    return { status: this.status, detail: this.detail };
  }

  async start(): Promise<void> {
    this.setStatus("probing", `探测 ${this.options.apiBaseUrl}`);
    const probe = await this.probe(this.options.apiBaseUrl);
    if (probe.reachable) {
      this.setStatus("external", `已连接 ${this.options.apiBaseUrl}`);
      this.startWatchdog();
      return;
    }
    const spawnRequested = process.env.REVIVE_DESKTOP_SPAWN_BACKEND === "1";
    const launcher = this.resolveLauncher();
    if (!spawnRequested || launcher === null) {
      this.setStatus(
        "failed",
        spawnRequested
          ? `未找到可启动的后端（${probe.detail}）`
          : `未连接到 ${this.options.apiBaseUrl}（${probe.detail}）；设置 REVIVE_DESKTOP_SPAWN_BACKEND=1 可让桌面版尝试拉起本地后端`,
      );
      this.startWatchdog();
      return;
    }
    this.setStatus("spawning", `启动 ${launcher.command} ${launcher.args.join(" ")}`);
    try {
      this.child = spawn(launcher.command, launcher.args, {
        cwd: launcher.cwd,
        env: { ...process.env, ...this.options.env },
        stdio: "ignore",
        windowsHide: true,
      });
    } catch (error) {
      this.setStatus("failed", `启动失败：${String(error)}`);
      return;
    }
    this.child.on("exit", (code) => {
      this.child = null;
      void this.recheck(`后端进程退出（code=${code ?? "null"}）`);
    });
    // Give uvicorn a moment, then confirm with a real probe instead of assuming success.
    await delay(2500);
    const after = await this.probe(this.options.apiBaseUrl);
    this.setStatus(after.reachable ? "external" : "failed", after.reachable ? `已由桌面版拉起 ${this.options.apiBaseUrl}` : `后端进程已启动但健康检查失败（${after.detail}）`);
    this.startWatchdog();
  }

  stop(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    if (this.child && !this.child.killed) {
      this.child.kill();
      this.child = null;
    }
  }

  private resolveLauncher(): { command: string; args: string[]; cwd: string } | null {
    const repoRoot = this.options.repoRoot;
    if (!repoRoot) return null;
    const python = join(repoRoot, ".venv", "Scripts", "python.exe");
    if (!existsSync(python)) return null;
    const apiSrc = resolve(repoRoot, "apps", "api", "src");
    if (!existsSync(apiSrc)) return null;
    const port = new URL(this.options.apiBaseUrl).port || "8000";
    return {
      command: python,
      args: ["-m", "uvicorn", "revive_api.main:app", "--host", "127.0.0.1", "--port", port],
      cwd: apiSrc,
    };
  }

  private async probe(baseUrl: string): Promise<ProbeResult> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 2000);
    try {
      const response = await fetch(new URL("/healthz", baseUrl), { signal: controller.signal });
      return { reachable: response.ok, detail: response.ok ? "ok" : `HTTP ${response.status}` };
    } catch (error) {
      return { reachable: false, detail: error instanceof Error ? error.message : String(error) };
    } finally {
      clearTimeout(timeout);
    }
  }

  private async recheck(reason: string): Promise<void> {
    const probe = await this.probe(this.options.apiBaseUrl);
    this.setStatus(probe.reachable ? "external" : "failed", probe.reachable ? `已连接 ${this.options.apiBaseUrl}` : reason);
  }

  private startWatchdog(): void {
    if (this.timer) return;
    this.timer = setInterval(() => {
      void this.recheck("健康检查失败");
    }, 30_000);
  }

  private setStatus(status: BackendStatus, detail: string | null): void {
    this.status = status;
    this.detail = detail;
    this.emit("status", status, detail);
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolveDelay) => setTimeout(resolveDelay, ms));
}
