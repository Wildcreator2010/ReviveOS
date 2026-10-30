"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiGet } from "../../api/client";
import { API_PATHS } from "../../api/paths";
import { readJob, readEvent } from "../../api/readers";
import type { JobEvent, JobStatus } from "../../api/domain-types";
import { JobEventStream, POLL_INTERVAL_MS, type StreamStatus } from "../../api/sse";
import { isTerminal } from "../../api/events";

/** Hard cap on retained events so a runaway stream cannot grow the DOM without bound. */
export const MAX_EVENTS = 2000;
const RENDER_WINDOW = 500;

function terminalStatus(event: JobEvent): JobStatus {
  const status = event.payload.status;
  if (status === "cancelled" || status === "succeeded" || status === "failed") return status;
  return event.type === "job.succeeded" ? "succeeded" : "failed";
}

export interface JobEventsState {
  events: JobEvent[];
  visible: JobEvent[];
  status: StreamStatus;
  detail: string | null;
  jobStatus: JobStatus;
  terminal: JobEvent | null;
  totalEvents: number;
  /** True when the stream gave up and the UI is polling GET /jobs/{id} instead. */
  degraded: boolean;
  lastEventId: string | null;
  reconnectNow: () => void;
}

/**
 * Live job feed: SSE with Last-Event-ID replay and capped exponential backoff;
 * after the retry budget is spent it degrades to polling the job resource and
 * says so explicitly in the UI (never an infinite spinner).
 */
export function useJobEvents(jobId: string): JobEventsState {
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const [detail, setDetail] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStatus>("unknown");
  const [terminal, setTerminal] = useState<JobEvent | null>(null);
  const [totalEvents, setTotalEvents] = useState(0);
  const [degraded, setDegraded] = useState(false);
  const [lastEventId, setLastEventId] = useState<string | null>(null);
  const [epoch, setEpoch] = useState(0);
  const seen = useRef<Set<string>>(new Set());
  const streamRef = useRef<JobEventStream | null>(null);
  const lastEventIdRef = useRef<string | null>(null);

  const push = useCallback((incoming: JobEvent) => {
    if (seen.current.has(incoming.id)) return; // idempotent replay
    seen.current.add(incoming.id);
    lastEventIdRef.current = incoming.id;
    setTotalEvents((count) => count + 1);
    setLastEventId(incoming.id);
    setEvents((current) => {
      const next = [...current, incoming];
      next.sort((a, b) => {
        const byTs = Date.parse(a.ts) - Date.parse(b.ts);
        return Number.isFinite(byTs) && byTs !== 0 ? byTs : a.id.localeCompare(b.id);
      });
      return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next;
    });
  }, []);

  useEffect(() => {
    if (!jobId) return;
    seen.current = new Set();
    lastEventIdRef.current = null;
    setEvents([]);
    setTerminal(null);
    setTotalEvents(0);
    setDegraded(false);
    setStatus("connecting");

    const stream = new JobEventStream(
      jobId,
      {
        onEvent: (event) => {
          push(event);
          if (isTerminal(event.type)) setTerminal(event);
        },
        onStatus: (next, why) => {
          setStatus(next);
          setDetail(why ?? null);
        },
        onTerminal: (event) => {
          setTerminal(event);
          setJobStatus(terminalStatus(event));
        },
      },
      {
        maxAttempts: 5,
        onExhausted: () => setDegraded(true),
      },
    );
    streamRef.current = stream;
    stream.start();
    return () => {
      stream.stop();
      streamRef.current = null;
    };
  }, [jobId, epoch, push]);

  // Fallback poller, active only in the degraded state.
  useEffect(() => {
    if (!degraded || !jobId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const payload = await apiGet<unknown>(API_PATHS.jobEvents(jobId), {
          query: { after: lastEventIdRef.current ?? undefined },
        });
        if (cancelled) return;
        const recent = Array.isArray(payload) ? payload : [];
        for (const entry of recent) {
          const event = readEvent(entry);
          if (!event) continue;
          push(event);
          if (isTerminal(event.type)) {
            setTerminal(event);
            setJobStatus(terminalStatus(event));
          }
        }
        if (Array.isArray(payload) && payload.length > 0) return;
        // Keep the JobResponse in sync even when there are no new events yet.
        const jobPayload = await apiGet<unknown>(API_PATHS.job(jobId));
        if (cancelled) return;
        const job = readJob(jobPayload);
        if (!job) return;
        setJobStatus(job.status);
        if (job.status === "succeeded" || job.status === "failed" || job.status === "cancelled") {
          setDetail((current) => current ?? `任务已${job.status === "succeeded" ? "成功" : "结束"}，事件流已降级为轮询`);
        }
      } catch {
        /* polling failure keeps the degraded banner visible */
      }
    };
    void tick();
    const handle = setInterval(() => void tick(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(handle);
    };
  }, [degraded, jobId, push]);

  const visible = useMemo(() => (events.length > RENDER_WINDOW ? events.slice(events.length - RENDER_WINDOW) : events), [events]);

  const reconnectNow = useCallback(() => {
    setDegraded(false);
    setEpoch((value) => value + 1);
  }, []);

  return { events, visible, status, detail, jobStatus, terminal, totalEvents, degraded, lastEventId, reconnectNow };
}
