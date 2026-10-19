"use client";

import { useEffect, useRef } from "react";
import { desktopBridge } from "../../desktop/bridge";
import type { JobEvent } from "../../api/domain-types";
import { EVENT_LABELS, isTerminal } from "../../api/events";

const NOTIFIABLE: readonly JobEvent["type"][] = ["build.failed", "repair.applied", "score.computed", "capsule.created", "job.succeeded", "job.failed"];

/**
 * Desktop task notifications.
 *
 * Only fired for events that actually arrived over the SSE stream (never from a
 * timer or a placeholder), terminal events always notify, and repeated identical
 * events are suppressed so a flapping build cannot spam the notification centre.
 */
export function useJobNotifications(jobId: string, events: JobEvent[]): void {
  const notified = useRef<Set<string>>(new Set());
  const bridge = desktopBridge();

  useEffect(() => {
    if (!bridge || events.length === 0) return;
    const last = events[events.length - 1];
    if (!last) return;
    if (!isTerminal(last.type) && !NOTIFIABLE.includes(last.type)) return;
    const key = `${last.type}:${last.id}`;
    if (notified.current.has(key)) return;
    // Suppress duplicate identical stages inside one job run.
    const stageKey = last.type;
    if (!isTerminal(last.type) && notified.current.has(stageKey)) return;
    notified.current.add(key);
    notified.current.add(stageKey);

    const summary = typeof last.payload.message === "string" ? last.payload.message : typeof last.payload.summary === "string" ? last.payload.summary : "";
    void bridge.notify({
      title: `任务 ${jobId.slice(0, 12)} · ${EVENT_LABELS[last.type]}`,
      body: summary.length > 0 ? summary : `${last.type} @ ${last.ts}`,
    });
  }, [bridge, events, jobId]);
}
