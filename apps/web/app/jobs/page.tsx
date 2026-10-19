"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { apiGet } from "../../src/api/client";
import { nextCursorOf, readJobs } from "../../src/api/readers";
import { describeApiError } from "../../src/api/useApi";
import { AsyncSection } from "../../components/ui/StateView";
import { JobRow } from "../../components/ui/Cards";

export default function JobsPage() {
  const [cursor, setCursor] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["jobs", cursor],
    queryFn: () => apiGet<unknown>("/api/v1/jobs", { query: { limit: 20, cursor: cursor ?? undefined } }),
  });
  const items = query.data ? readJobs(query.data) : [];
  const nextCursor = query.data ? nextCursorOf(query.data) : null;

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <p className="eyebrow">JOBS</p>
          <h1>任务</h1>
          <p className="muted small" style={{ margin: 0 }}>
            来自 GET /api/v1/jobs
          </p>
        </div>
        <button type="button" className="btn btn-ghost" onClick={() => void query.refetch()} disabled={query.isFetching}>
          {query.isFetching ? "刷新中…" : "刷新"}
        </button>
      </div>

      <AsyncSection
        loading={query.isPending}
        error={query.error ? describeApiError(query.error) : null}
        empty={query.data && items.length === 0 ? { title: "还没有任务", reason: "控制面没有返回任务记录。", next: null } : null}
      >
        <table>
          <thead>
            <tr>
              <th>任务</th>
              <th>项目</th>
              <th>状态</th>
              <th>创建</th>
              <th>结束</th>
              <th>错误码</th>
            </tr>
          </thead>
          <tbody>
            {items.map((job) => (
              <JobRow key={job.id} job={job} />
            ))}
          </tbody>
        </table>
        <div className="row" style={{ marginTop: 16 }}>
          <button type="button" className="btn btn-ghost" disabled={cursor === null} onClick={() => setCursor(null)}>
            回到首页
          </button>
          <button type="button" className="btn" disabled={nextCursor === null} onClick={() => setCursor(nextCursor)}>
            {nextCursor === null ? "没有更多" : "下一页"}
          </button>
        </div>
      </AsyncSection>
    </section>
  );
}
