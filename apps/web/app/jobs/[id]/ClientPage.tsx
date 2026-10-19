"use client";


import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiGet, apiPost } from "../../../src/api/client";
import { readJob } from "../../../src/api/readers";
import { describeApiError } from "../../../src/api/useApi";
import { pickStr, str } from "../../../src/api/domain";
import { JobStatusBadge, Tile, formatTimestamp } from "../../../components/ui/Cards";
import { StatusBadge } from "../../../components/ui/StatusBadge";
import { EmptyState } from "../../../components/ui/StateView";
import { Timeline } from "../../../src/features/live/Timeline";
import { useJobEvents, MAX_EVENTS } from "../../../src/features/live/useJobEvents";
import { useJobNotifications } from "../../../src/features/live/useJobNotifications";

const STREAM_LABELS: Record<string, string> = {
  connecting: "连接事件流…",
  open: "事件流已连接",
  reconnecting: "正在重连",
  closed: "事件流已关闭",
  degraded: "事件流已降级为轮询",
  fatal: "事件流不可用",
};

export default function JobLivePage() {
  const params = useParams<{ id: string }>();
  const jobId = typeof params.id === "string" ? params.id : "";
  const queryClient = useQueryClient();
  const stream = useJobEvents(jobId);
  // Desktop only; a no-op in the browser. Fires exclusively on real SSE events.
  useJobNotifications(jobId, stream.visible);

  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => apiGet<unknown>(`/api/v1/jobs/${encodeURIComponent(jobId)}`),
    enabled: jobId.length > 0,
    refetchInterval: stream.degraded ? 5000 : false,
  });
  const summary = job.data ? readJob(job.data) : null;
  const effectiveStatus = stream.terminal ? (stream.terminal.type === "job.succeeded" ? "succeeded" : "failed") : stream.jobStatus !== "unknown" ? stream.jobStatus : (summary?.status ?? "unknown");

  const cancel = useMutation({
    mutationFn: () => apiPost<unknown>(`/api/v1/jobs/${encodeURIComponent(jobId)}/cancel`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["job", jobId] });
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const cancelError = cancel.error instanceof ApiError ? cancel.error.message : cancel.error ? String(cancel.error) : null;

  const terminalCapsuleId = stream.terminal ? (str(stream.terminal.payload.capsule_id) ?? pickStr(stream.terminal.payload, "capsule.id")) : null;

  const eventGroups = new Map<string, number>();
  for (const event of stream.events) eventGroups.set(event.type, (eventGroups.get(event.type) ?? 0) + 1);

  return (
    <div className="stack">
      <section className="panel">
        <div className="spread">
          <div>
            <p className="eyebrow">JOB · LIVE ICU MONITOR</p>
            <h1 className="mono">{jobId}</h1>
            <p className="muted small" style={{ margin: 0 }}>
              订阅 GET /api/v1/jobs/&#123;id&#125;/events/stream（SSE，Last-Event-ID 断线重放）。
            </p>
          </div>
          <div className="row">
            <JobStatusBadge status={effectiveStatus} />
            <StatusBadge state={stream.status === "open" ? "running" : stream.status === "degraded" || stream.status === "fatal" ? "dead" : "partial"} label={STREAM_LABELS[stream.status] ?? stream.status} />
          </div>
        </div>

        <div className="grid-4" style={{ marginTop: 16 }}>
          <Tile label="已接收事件" value={stream.totalEvents} tone="running" hint={`最多保留 ${MAX_EVENTS} 条，超出丢弃最旧事件。`} />
          <Tile label="当前事件类型" value={stream.events.length > 0 ? String(stream.events[stream.events.length - 1]?.type) : "—"} />
          <Tile label="创建时间" value={<span style={{ fontSize: 13 }}>{formatTimestamp(summary?.createdAt ?? null)}</span>} />
          <Tile label="结束时间" value={<span style={{ fontSize: 13 }}>{formatTimestamp(summary?.finishedAt ?? null)}</span>} />
        </div>

        <div className="row" style={{ marginTop: 12 }}>
          <button type="button" className="btn" onClick={() => void job.refetch()} disabled={job.isFetching}>
            刷新任务资源
          </button>
          <button type="button" className="btn btn-danger" onClick={() => cancel.mutate()} disabled={cancel.isPending || effectiveStatus === "succeeded" || effectiveStatus === "failed"}>
            {cancel.isPending ? "取消中…" : "取消任务"}
          </button>
          {summary?.projectId ? (
            <Link className="btn btn-ghost" href={`/projects/${encodeURIComponent(summary.projectId)}`}>
              打开项目
            </Link>
          ) : null}
          <button type="button" className="btn btn-ghost" onClick={stream.reconnectNow}>
            立即重连
          </button>
        </div>

        {stream.detail ? <p className="muted small mono" style={{ marginTop: 8 }}>{stream.detail}</p> : null}
        {stream.degraded ? (
          <div className="banner banner-partial" style={{ marginTop: 12 }} role="status">
            <strong>SSE 重连次数已用尽，已降级为轮询</strong>
            <p className="small" style={{ margin: "6px 0 0" }}>
              每 5 秒读取一次 GET /api/v1/jobs/&#123;id&#125;。降级期间仍会按事件 id 去重，不会重复渲染。
            </p>
          </div>
        ) : null}
        {cancelError ? <p className="small fatal" role="alert">{cancelError}</p> : null}
        {job.error && !stream.degraded ? (
          <p className="small muted">任务资源暂不可读：{describeApiError(job.error).code}</p>
        ) : null}
      </section>

      {stream.terminal ? (
        <section className="panel" data-tone={stream.terminal.type === "job.succeeded" ? "alive" : "dead"}>
          <h2>终态汇总</h2>
          <div className="row">
            <StatusBadge state={stream.terminal.type === "job.succeeded" ? "alive" : "dead"} label={stream.terminal.type === "job.succeeded" ? "任务成功" : "任务失败"} />
            <span className="mono small">{stream.terminal.ts}</span>
          </div>
          <p className="small" style={{ marginTop: 8 }}>
            {pickStr(stream.terminal.payload, "message") ?? pickStr(stream.terminal.payload, "summary") ?? "终态事件未携带摘要文本，展开原始 JSON 查看 payload。"}
          </p>
          <div className="row">
            {stream.terminal.type === "job.succeeded" ? (
              <Link className="btn" href={summary?.projectId ? `/projects/${encodeURIComponent(summary.projectId)}/report` : "/projects"}>
                查看复生评分
              </Link>
            ) : null}
            {terminalCapsuleId ? (
              <Link className="btn btn-ghost" href={`/capsules/${encodeURIComponent(terminalCapsuleId)}`}>
                打开胶囊
              </Link>
            ) : null}
          </div>
        </section>
      ) : null}

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>事件时间线</h2>
            <p className="muted small" style={{ margin: 0 }}>
              按事件类型分组；原始 JSON 可展开查看。最多渲染最近 500 条（共接收 {stream.totalEvents} 条）。
            </p>
          </div>
          <span className="muted small mono">last-event-id {stream.lastEventId ?? "—"}</span>
        </div>
        {stream.visible.length >= 500 && stream.totalEvents > stream.visible.length ? (
          <p className="muted small">已折叠较早的事件以保持渲染稳定；完整序列请查看任务产物或事件表。</p>
        ) : null}
        {stream.status === "degraded" && stream.visible.length === 0 ? (
          <EmptyState title="降级状态下尚无事件" reason="轮询尚未取回任何事件，或该任务确实没有事件记录。" />
        ) : (
          <Timeline events={stream.visible} follow />
        )}
      </section>

      {eventGroups.size > 0 ? (
        <section className="panel">
          <h2>事件计数</h2>
          <table>
            <thead>
              <tr>
                <th>类型</th>
                <th>数量</th>
              </tr>
            </thead>
            <tbody>
              {[...eventGroups.entries()].map(([type, count]) => (
                <tr key={type}>
                  <td className="mono small">{type}</td>
                  <td className="mono">{count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
    </div>
  );
}
