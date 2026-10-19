import type { EventType } from "./domain-types";

export const EVENT_TYPES = [
  "job.queued",
  "archaeology.started",
  "archaeology.evidence",
  "env.inferred",
  "sandbox.created",
  "build.attempt",
  "build.failed",
  "repair.attempt",
  "repair.applied",
  "test.attempt",
  "behavior.captured",
  "behavior.compared",
  "score.computed",
  "capsule.created",
  "job.succeeded",
  "job.failed",
] as const satisfies readonly EventType[];

export function isEventType(value: unknown): value is EventType {
  return typeof value === "string" && (EVENT_TYPES as readonly string[]).includes(value);
}

export type EventGroup = "archaeology" | "environment" | "sandbox" | "build" | "repair" | "test" | "behavior" | "score" | "capsule" | "job";

export const GROUP_OF: Record<EventType, EventGroup> = {
  "job.queued": "job",
  "archaeology.started": "archaeology",
  "archaeology.evidence": "archaeology",
  "env.inferred": "environment",
  "sandbox.created": "sandbox",
  "build.attempt": "build",
  "build.failed": "build",
  "repair.attempt": "repair",
  "repair.applied": "repair",
  "test.attempt": "test",
  "behavior.captured": "behavior",
  "behavior.compared": "behavior",
  "score.computed": "score",
  "capsule.created": "capsule",
  "job.succeeded": "job",
  "job.failed": "job",
};

export const GROUP_LABELS: Record<EventGroup, string> = {
  job: "任务",
  archaeology: "考古",
  environment: "环境",
  sandbox: "沙箱",
  build: "构建",
  repair: "修复",
  test: "测试",
  behavior: "行为",
  score: "评分",
  capsule: "胶囊",
};

export const EVENT_LABELS: Record<EventType, string> = {
  "job.queued": "任务入队",
  "archaeology.started": "考古开始",
  "archaeology.evidence": "考古证据",
  "env.inferred": "环境推断",
  "sandbox.created": "沙箱就绪",
  "build.attempt": "构建尝试",
  "build.failed": "构建失败",
  "repair.attempt": "修复尝试",
  "repair.applied": "修复已应用",
  "test.attempt": "测试运行",
  "behavior.captured": "行为采集",
  "behavior.compared": "行为比对",
  "score.computed": "评分完成",
  "capsule.created": "胶囊产出",
  "job.succeeded": "任务成功",
  "job.failed": "任务失败",
};

export const TERMINAL_EVENT_TYPES: readonly EventType[] = ["job.succeeded", "job.failed"];

export function isTerminal(type: EventType): boolean {
  return TERMINAL_EVENT_TYPES.includes(type);
}

/** Highlights an event row as an incident (red) vs. normal progress (blue). */
export function isIncident(type: EventType): boolean {
  return type === "build.failed" || type === "job.failed";
}

export function isSuccess(type: EventType): boolean {
  return type === "job.succeeded";
}
