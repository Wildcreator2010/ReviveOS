/**
 * Domain view types for the console.
 *
 * These describe values the UI is allowed to read — they are NOT the generated
 * OpenAPI components (those are blocked until schemas/openapi/openapi.json lands).
 * Every field is optional/nullable so a partial backend payload degrades into an
 * explicit empty state rather than a wrong number.
 */

/** Mirrors schemas/job-event.schema.json (the one frozen event contract). */
export type EventType =
  | "job.queued"
  | "archaeology.started"
  | "archaeology.evidence"
  | "env.inferred"
  | "sandbox.created"
  | "build.attempt"
  | "build.failed"
  | "repair.attempt"
  | "repair.applied"
  | "test.attempt"
  | "behavior.captured"
  | "behavior.compared"
  | "score.computed"
  | "capsule.created"
  | "job.succeeded"
  | "job.failed";

export interface JobEvent {
  id: string;
  job_id: string;
  project_id: string;
  ts: string;
  type: EventType;
  payload: Record<string, unknown>;
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "cancel_requested" | "unknown";

export type CapsuleStatus = "alive" | "partial" | "dead" | "unknown";

export type StatusTone = "alive" | "partial" | "dead" | "running" | "neutral";

export function toneForJobStatus(status: JobStatus): StatusTone {
  switch (status) {
    case "queued":
    case "running":
    case "cancel_requested":
      return "running";
    case "succeeded":
      return "alive";
    case "failed":
      return "dead";
    case "cancelled":
      return "partial";
    default:
      return "neutral";
  }
}

export function toneForCapsuleStatus(status: CapsuleStatus): StatusTone {
  switch (status) {
    case "alive":
      return "alive";
    case "partial":
      return "partial";
    case "dead":
      return "dead";
    default:
      return "neutral";
  }
}

export const JOB_STATUS_LABELS: Record<JobStatus, string> = {
  queued: "排队中",
  running: "进行中",
  succeeded: "成功",
  failed: "失败",
  cancelled: "已取消",
  cancel_requested: "取消中",
  unknown: "未知",
};

export const CAPSULE_STATUS_LABELS: Record<CapsuleStatus, string> = {
  alive: "ALIVE",
  partial: "PARTIAL",
  dead: "DEAD",
  unknown: "未知",
};
