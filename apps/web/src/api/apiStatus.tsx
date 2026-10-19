"use client";

import { useQuery } from "@tanstack/react-query";
import { apiBaseUrl, apiGet } from "../api/client";
import { API_PATHS } from "./paths";
import { readJob } from "./readers";

const HEALTH_POLL_MS = 20_000;

export interface ApiHealth {
  reachable: boolean;
  ready: boolean | null;
  readyComponents: Record<string, string> | null;
  detail: string | null;
  checkedAt: string | null;
}

/** Lightweight liveness+readiness probe (GET /healthz, GET /readyz). */
export function useApiHealth(): ApiHealth & { refresh: () => void } {
  const query = useQuery({
    queryKey: ["api-health"],
    refetchInterval: HEALTH_POLL_MS,
    queryFn: async (): Promise<ApiHealth> => {
      try {
        await apiGet<unknown>(API_PATHS.health);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        return { reachable: false, ready: null, readyComponents: null, detail: message, checkedAt: new Date().toISOString() };
      }
      let ready: boolean | null = null;
      let components: Record<string, string> | null = null;
      let detail: string | null = null;
      try {
        const payload = (await apiGet<unknown>(API_PATHS.ready)) as { components?: Record<string, string> } | null;
        ready = true;
        components = payload && typeof payload === "object" ? (payload.components ?? null) : null;
      } catch (error) {
        ready = false;
        const details = (error as { details?: Record<string, unknown> }).details;
        const raw = details && typeof details.detail === "object" && details.detail !== null ? (details.detail as Record<string, unknown>) : null;
        components = raw && typeof raw.components === "object" && raw.components !== null ? (raw.components as Record<string, string>) : null;
        detail = error instanceof Error ? error.message : String(error);
      }
      return { reachable: true, ready, readyComponents: components, detail, checkedAt: new Date().toISOString() };
    },
  });
  const data = query.data;
  return {
    reachable: data?.reachable ?? false,
    ready: data?.ready ?? null,
    readyComponents: data?.readyComponents ?? null,
    detail: data?.detail ?? (query.isLoading ? "正在探测…" : null),
    checkedAt: data?.checkedAt ?? null,
    refresh: () => void query.refetch(),
  };
}

export function ApiStatusChip() {
  const health = useApiHealth();
  const state = !health.reachable ? "dead" : health.ready === false ? "partial" : "alive";
  const label = !health.reachable ? "控制面离线" : health.ready === false ? "控制面降级" : "控制面在线";
  const glyph = state === "alive" ? "●" : state === "partial" ? "◐" : "○";
  return (
    <span className="badge" data-tone={state} title={health.detail ?? apiBaseUrl()}>
      <span className="dot" aria-hidden="true" />
      <span aria-hidden="true">{glyph}</span>
      <span>{label}</span>
    </span>
  );
}

/** Recent jobs widget shared by the ICU dashboard. */
export function RecentJobsProbe() {
  const query = useQuery({
    queryKey: ["recent-jobs"],
    queryFn: () => apiGet<unknown>(API_PATHS.jobs, { query: { limit: 5 } }),
  });
  if (query.isLoading) return <p className="muted small">正在读取任务…</p>;
  if (query.isError) return null;
  const jobs = Array.isArray(query.data) ? query.data : [];
  return <p className="muted small">最近 {jobs.map((job) => readJob(job)?.id ?? "?").join("、") || "无任务"}</p>;
}
