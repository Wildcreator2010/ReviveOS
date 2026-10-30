import { apiUrl, getAccessToken, refreshAccessToken } from "./client";
import { API_PATHS } from "./paths";
import { readEvent } from "./readers";
import type { JobEvent } from "./domain-types";

export type StreamStatus = "connecting" | "open" | "reconnecting" | "closed" | "fatal" | "degraded";

export interface StreamCallbacks {
  onEvent: (event: JobEvent) => void;
  onStatus: (status: StreamStatus, detail?: string) => void;
  /** Terminal event observed — the server closes the stream right after it. */
  onTerminal?: (event: JobEvent) => void;
}

export interface StreamOptions {
  /** Max consecutive reconnect attempts before degrading to polling (task spec: <= 5). */
  maxAttempts?: number;
  baseDelayMs?: number;
  maxDelayMs?: number;
  onExhausted?: (reason: string) => void;
}

const DEFAULTS: Required<Omit<StreamOptions, "onExhausted">> = {
  maxAttempts: 5,
  baseDelayMs: 1000,
  maxDelayMs: 20000,
};

/** Polling fallback used once SSE reconnect attempts are exhausted (explicitly labelled in the UI). */
export const POLL_INTERVAL_MS = 5000;

/**
 * SSE consumer for GET /api/v1/jobs/{id}/events/stream.
 *
 * Uses fetch + ReadableStream rather than EventSource so that an in-memory
 * Bearer token / X-Revive-Key header can be attached (EventSource cannot send
 * custom headers), and so Last-Event-ID replay is fully under our control.
 * Reconnects with exponential backoff, capped, then reports exhaustion so the
 * caller can degrade to polling instead of spinning forever.
 */
export class JobEventStream {
  private controller: AbortController | null = null;
  private attempt = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private closed = false;
  private lastEventId: string | null = null;
  private authRetried = false;
  private sawTerminal = false;
  private readonly options: Required<Omit<StreamOptions, "onExhausted">> & Pick<StreamOptions, "onExhausted">;

  constructor(
    private readonly jobId: string,
    private readonly callbacks: StreamCallbacks,
    options: StreamOptions = {},
  ) {
    this.options = {
      maxAttempts: Math.min(options.maxAttempts ?? DEFAULTS.maxAttempts, DEFAULTS.maxAttempts),
      baseDelayMs: options.baseDelayMs ?? DEFAULTS.baseDelayMs,
      maxDelayMs: options.maxDelayMs ?? DEFAULTS.maxDelayMs,
      onExhausted: options.onExhausted,
    };
  }

  get lastId(): string | null {
    return this.lastEventId;
  }

  start(): void {
    this.closed = false;
    this.sawTerminal = false;
    void this.connect();
  }

  stop(): void {
    this.closed = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.controller?.abort();
    this.controller = null;
    this.callbacks.onStatus("closed");
  }

  private async connect(): Promise<void> {
    if (this.closed) return;
    this.controller = new AbortController();
    this.callbacks.onStatus(this.attempt === 0 ? "connecting" : "reconnecting");
    const headers: Record<string, string> = { Accept: "text/event-stream" };
    const token = getAccessToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    if (this.lastEventId) headers["Last-Event-ID"] = this.lastEventId;
    try {
      const response = await fetch(apiUrl(API_PATHS.jobEventsStream(this.jobId)), {
        headers,
        credentials: "include",
        signal: this.controller.signal,
      });
      if (response.status === 401 && !this.authRetried) {
        this.authRetried = true;
        if (await refreshAccessToken()) {
          await this.connect();
          return;
        }
      }
      if (response.status === 404 || response.status === 410) {
        this.closed = true;
        this.callbacks.onStatus("fatal", `事件流不可用（${response.status}）`);
        return;
      }
      if (!response.ok || !response.body) {
        throw new Error(`stream_status_${response.status}`);
      }
      this.attempt = 0;
      this.authRetried = false;
      this.callbacks.onStatus("open");
      await this.consume(response.body);
      // A terminal event closes the stream deliberately; anything else is an
      // interrupted live feed and must reconnect (or degrade to polling).
      if (!this.closed) {
        if (!this.sawTerminal) {
          this.scheduleRetry("事件流在终态前关闭");
          return;
        }
        this.closed = true;
        this.callbacks.onStatus("closed");
      }
    } catch (error) {
      if (this.closed) return;
      const reason = error instanceof Error ? error.message : String(error);
      if (reason === "aborted" || (error instanceof DOMException && error.name === "AbortError")) return;
      this.scheduleRetry(reason);
    }
  }

  private scheduleRetry(reason: string): void {
    if (this.closed) return;
    if (this.attempt >= this.options.maxAttempts) {
      this.closed = true;
      this.callbacks.onStatus("degraded", reason);
      this.options.onExhausted?.(reason);
      return;
    }
    const attempt = this.attempt + 1;
    this.attempt = attempt;
    const delay = Math.min(this.options.baseDelayMs * 2 ** (attempt - 1), this.options.maxDelayMs);
    this.callbacks.onStatus("reconnecting", `第 ${attempt}/${this.options.maxAttempts} 次重连，${Math.round(delay / 1000)}s 后`);
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.connect();
    }, delay);
  }

  private async consume(body: ReadableStream<Uint8Array>): Promise<void> {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    // sse-starlette separates frames with CRLF; browsers accept both. Never
    // assume a bare "\n\n" or every frame is silently dropped.
    const boundary = /\r?\n\r?\n/;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let match = boundary.exec(buffer);
      while (match) {
        const chunk = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);
        this.handleFrame(chunk);
        match = boundary.exec(buffer);
      }
    }
  }

  private handleFrame(frame: string): void {
    const dataLines: string[] = [];
    for (const rawLine of frame.split(/\r?\n/)) {
      const line = rawLine.trimEnd();
      if (line.length === 0 || line.startsWith(":")) continue; // comment / heartbeat
      if (line.startsWith("id:")) {
        this.lastEventId = line.slice(3).trim();
        continue;
      }
      if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
    }
    if (dataLines.length === 0) return;
    const payload = dataLines.join("\n");
    let parsed: unknown;
    try {
      parsed = JSON.parse(payload);
    } catch {
      return;
    }
    const event = readEvent(parsed);
    if (!event) return;
    this.lastEventId = event.id;
    this.callbacks.onEvent(event);
    if (event.type === "job.succeeded" || event.type === "job.failed") {
      this.sawTerminal = true;
      this.callbacks.onTerminal?.(event);
    }
  }
}
