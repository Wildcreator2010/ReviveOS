"use client";


import Link from "next/link";
import { useRouteId } from "../../../src/api/routeParams";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../../../src/api/client";
import { readJobs, readProject } from "../../../src/api/readers";
import { describeApiError } from "../../../src/api/useApi";
import { AsyncSection } from "../../../components/ui/StateView";
import { JobRow, Tile, formatTimestamp } from "../../../components/ui/Cards";
import { ProjectTabs } from "../../../src/features/projects/ProjectTabs";

export default function ProjectDetailPage() {
  const projectId = useRouteId("projects");

  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => apiGet<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}`),
    enabled: projectId.length > 0,
  });
  const jobs = useQuery({
    queryKey: ["project-jobs", projectId],
    queryFn: () => apiGet<unknown>("/api/v1/jobs", { query: { project_id: projectId, limit: 20 } }),
    enabled: projectId.length > 0,
  });

  const summary = project.data ? readProject(project.data) : null;
  const jobList = jobs.data ? readJobs(jobs.data) : [];

  return (
    <div className="stack">
      <section className="panel">
        <p className="eyebrow">PROJECT</p>
        <h1 className="mono">{summary?.repo ?? projectId}</h1>
        <p className="muted small mono">{projectId}</p>
        <ProjectTabs projectId={projectId} />
        <AsyncSection
          loading={project.isPending}
          error={project.error ? describeApiError(project.error) : null}
          empty={project.data && !summary ? { title: "无法解析项目", reason: "API 返回的对象缺少 id 字段，读取器按契约拒绝渲染。", next: null } : null}
        >
          <div className="grid-4">
            <Tile label="仓库" value={<span className="mono" style={{ fontSize: 14 }}>{summary?.repoUrl ?? "未知"}</span>} />
            <Tile label="状态" value={summary?.status ?? "未知"} tone={summary?.status === "alive" ? "alive" : summary?.status === "dead" ? "dead" : summary?.status === "partial" ? "partial" : "neutral"} />
            <Tile label="最新评分" value={summary?.latestScore ?? "—"} tone={summary?.latestScore === null || summary?.latestScore === undefined ? "neutral" : summary.latestScore >= 80 ? "alive" : summary.latestScore >= 50 ? "partial" : "dead"} hint="直接显示 API 的 latest_score，前端不重算。" />
            <Tile label="最近更新" value={<span style={{ fontSize: 14 }}>{formatTimestamp(summary?.updatedAt ?? null)}</span>} />
          </div>
        </AsyncSection>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>复生时间线</h2>
            <p className="muted small" style={{ margin: 0 }}>
              来自 GET /api/v1/jobs?project_id=…
            </p>
          </div>
          <Link className="btn btn-ghost" href="/">
            新建任务
          </Link>
        </div>
        <AsyncSection
          loading={jobs.isPending}
          error={jobs.error ? describeApiError(jobs.error) : null}
          empty={jobs.data && jobList.length === 0 ? { title: "该项目还没有任务", reason: "历次复生 job 会按时间出现在这里。", next: null } : null}
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
              {jobList.map((job) => (
                <JobRow key={job.id} job={job} />
              ))}
            </tbody>
          </table>
        </AsyncSection>
      </section>
    </div>
  );
}
