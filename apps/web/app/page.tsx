"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { apiGet } from "../src/api/client";
import { API_PATHS } from "../src/api/paths";
import { useApiHealth } from "../src/api/apiStatus";
import { readJobs, readProjects, readJob } from "../src/api/readers";
import { describeApiError } from "../src/api/useApi";
import { AsyncSection, EmptyState, OfflineState } from "../components/ui/StateView";
import { JobRow, Tile } from "../components/ui/Cards";
import { ResurrectForm } from "../src/features/submit/ResurrectForm";
import { StatusBadge } from "../components/ui/StatusBadge";

export default function HomePage() {
  const health = useApiHealth();
  const projects = useQuery({
    queryKey: ["projects", "icu"],
    queryFn: () => apiGet<unknown>(API_PATHS.projects, { query: { limit: 100 } }),
  });
  const jobs = useQuery({
    queryKey: ["jobs", "icu"],
    queryFn: () => apiGet<unknown>(API_PATHS.jobs, { query: { limit: 8 } }),
  });

  const projectList = projects.data ? readProjects(projects.data) : [];
  const jobList = jobs.data ? readJobs(jobs.data) : [];
  const running = jobList.filter((job) => job.status === "running" || job.status === "queued").length;
  const finished = jobList.filter((job) => job.status === "succeeded" || job.status === "failed").length;
  // Displays the API-provided totals; the average is an explicit, labelled aggregation of
  // values returned by the API (the score itself is never recomputed in the frontend).
  const scored = projectList.filter((project) => project.latestScore !== null);
  const averageScore = scored.length > 0 ? scored.reduce((sum, project) => sum + (project.latestScore ?? 0), 0) / scored.length : null;
  const offline = health.reachable === false || (projects.error ? describeApiError(projects.error).offline : false) || (jobs.error ? describeApiError(jobs.error).offline : false);

  return (
    <div className="stack">
      <section className="panel dashboard-hero">
        <div className="hero-orbit" aria-hidden="true"><span /><span /><span /></div>
        <p className="eyebrow">REVIVEOS / SOFTWARE ICU</p>
        <div className="spread">
          <div>
            <h1>软件重症监护室</h1>
            <p className="muted">
              提交一个仓库地址，观察考古 → 环境推断 → 沙箱构建 → 修复 → 行为比对 → 复生评分的全过程。所有数字均来自 API，前端不重算评分。
            </p>
          </div>
          <StatusBadge
            state={!health.reachable ? "dead" : health.ready === false ? "partial" : "alive"}
            label={!health.reachable ? "控制面离线" : health.ready === false ? "控制面降级" : "控制面在线"}
            title={health.detail ?? undefined}
          />
        </div>

        {offline ? <OfflineState apiUrl={health.detail ?? ""} onRetry={() => { health.refresh(); void projects.refetch(); void jobs.refetch(); }} /> : null}

        <div className="grid-4" style={{ marginTop: 16 }}>
          <Tile label="项目" value={projects.isPending ? "…" : projectList.length} tone="neutral" />
          <Tile label="进行中任务" value={jobs.isPending ? "…" : running} tone="running" />
          <Tile label="已结束任务" value={jobs.isPending ? "…" : finished} tone="neutral" />
          <Tile
            label="平均评分(前端聚合)"
            value={averageScore === null ? "—" : averageScore.toFixed(1)}
            tone={averageScore === null ? "neutral" : averageScore >= 80 ? "alive" : averageScore >= 50 ? "partial" : "dead"}
            hint={`由 API 返回的 ${scored.length} 个项目 latest_score 取算术平均；单个项目的总分永远直接显示 API 值。`}
          />
        </div>

        {health.ready === false && health.readyComponents ? (
          <div className="banner banner-partial" style={{ marginTop: 16 }}>
            <strong>依赖组件未就绪</strong>
            <p className="mono small" style={{ margin: "6px 0 0" }}>
              {Object.entries(health.readyComponents).map(([name, status]) => `${name}=${status}`).join(" · ")}
            </p>
          </div>
        ) : null}
      </section>

      <ResurrectForm />

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>最近任务</h2>
            <p className="muted small" style={{ margin: 0 }}>
              来自 GET /api/v1/jobs?limit=8
            </p>
          </div>
          <Link className="btn btn-ghost" href="/jobs">
            全部任务
          </Link>
        </div>
        <AsyncSection
          loading={jobs.isPending}
          error={jobs.error ? describeApiError(jobs.error) : null}
          empty={
            jobs.data && jobList.length === 0
              ? { title: "还没有任务", reason: "控制面未返回任何 job 记录。提交一个仓库后，任务会出现在这里。", next: null }
              : null
          }
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

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>项目</h2>
            <p className="muted small" style={{ margin: 0 }}>
              来自 GET /api/v1/projects?limit=100
            </p>
          </div>
          <Link className="btn btn-ghost" href="/projects">
            全部项目
          </Link>
        </div>
        <AsyncSection
          loading={projects.isPending}
          error={projects.error ? describeApiError(projects.error) : null}
          empty={
            projects.data && projectList.length === 0
              ? { title: "还没有项目", reason: "在上方提交 GitHub 仓库地址即可创建第一个项目。", next: null }
              : null
          }
        >
          <div className="list">
            {projectList.slice(0, 6).map((project) => (
              <div key={project.id} className="list-item">
                <Link href={`/projects/${encodeURIComponent(project.id)}`}>{project.repo ?? project.repoUrl ?? project.id}</Link>
                <span className="muted small mono" style={{ marginLeft: 10 }}>
                  {project.latestScore === null ? "无评分" : `score ${project.latestScore}`}
                </span>
              </div>
            ))}
          </div>
        </AsyncSection>
      </section>

      <section className="panel">
        <h2>数据来源声明</h2>
        <p className="muted small">
          本控制台只渲染 API 返回值。OpenAPI 快照（schemas/openapi/openapi.json）尚未由后端发布，因此
          apps/web/src/api/types.gen.ts 中的领域类型仍是占位：页面通过 src/api/readers.ts 的运行时读取器取值，缺失字段显示为「未知 / API 未提供」，绝不填充示例数据。
        </p>
      </section>
    </div>
  );
}
