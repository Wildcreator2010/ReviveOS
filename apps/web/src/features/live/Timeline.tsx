"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { JobEvent } from "../../api/domain-types";
import { EVENT_LABELS, GROUP_LABELS, GROUP_OF, isIncident, isSuccess, type EventGroup } from "../../api/events";

export interface TimelineProps {
  events: JobEvent[];
  /** Group headers collapse per stage; the header always shows the count. */
  grouped?: boolean;
  /** Auto-scroll to the newest event unless the operator scrolled up. */
  follow?: boolean;
}

function payloadSummary(event: JobEvent): string | null {
  const candidates = ["message", "summary", "error_fact.signature", "stderr_excerpt", "detail", "reason"];
  for (const key of candidates) {
    const parts = key.split(".");
    let cursor: unknown = event.payload;
    for (const part of parts) {
      if (typeof cursor !== "object" || cursor === null) {
        cursor = undefined;
        break;
      }
      cursor = (cursor as Record<string, unknown>)[part];
    }
    if (typeof cursor === "string" && cursor.length > 0) return cursor;
  }
  return null;
}

function toneOf(event: JobEvent): "alive" | "dead" | "running" {
  if (isSuccess(event.type)) return "alive";
  if (isIncident(event.type)) return "dead";
  return "running";
}

export function EventCard({ event, defaultOpen = false }: { event: JobEvent; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const summary = payloadSummary(event);
  const json = useMemo(() => JSON.stringify(event.payload, null, 2), [event.payload]);
  return (
    <article className="event" data-tone={toneOf(event)}>
      <div className="event-head">
        <span className="event-type">{event.type}</span>
        <span>{EVENT_LABELS[event.type]}</span>
        <span className="event-ts">{event.ts || "时间未知"}</span>
        <span className="header-spacer" />
        <button type="button" className="btn btn-ghost small" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? "收起" : "原始 JSON"}
        </button>
      </div>
      {summary ? <p className="small" style={{ margin: "6px 0 0" }}>{summary}</p> : null}
      {open ? <pre className="payload">{json}</pre> : null}
    </article>
  );
}

export function Timeline({ events, grouped = true, follow = true }: TimelineProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [pinned, setPinned] = useState(true);

  useEffect(() => {
    if (!follow || !pinned) return;
    const node = containerRef.current;
    if (!node) return;
    const target = node.querySelector("[data-last-event]");
    if (target instanceof HTMLElement) target.scrollIntoView({ block: "nearest" });
  }, [events, follow, pinned]);

  if (events.length === 0) {
    return (
      <p className="muted">
        还没有事件。若任务正在跑，事件会通过 SSE 实时出现；若长时间没有事件，请检查控制面是否可达（顶部状态徽章 / 设置页）。
      </p>
    );
  }

  if (!grouped) {
    return (
      <div className="timeline" ref={containerRef} onScroll={() => setPinned(false)}>
        {events.map((event, index) => (
          <div key={event.id} data-last-event={index === events.length - 1 ? "" : undefined}>
            <EventCard event={event} />
          </div>
        ))}
      </div>
    );
  }

  const groups = new Map<EventGroup, JobEvent[]>();
  for (const event of events) {
    const group = GROUP_OF[event.type];
    const bucket = groups.get(group);
    if (bucket) bucket.push(event);
    else groups.set(group, [event]);
  }

  return (
    <div className="stack" ref={containerRef}>
      {[...groups.entries()].map(([group, groupEvents]) => (
        <section key={group}>
          <h3 className="mono" style={{ color: "var(--muted)" }}>
            {GROUP_LABELS[group]} · {groupEvents.length}
          </h3>
          <div className="timeline">
            {groupEvents.map((event, index) => (
              <div key={event.id} data-last-event={index === groupEvents.length - 1 ? "" : undefined}>
                <EventCard event={event} />
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
