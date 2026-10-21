"use client";


import { useApiQuery } from "../../../../src/api/useApi";
import { describeApiError } from "../../../../src/api/useApi";
import { readScore } from "../../../../src/api/readers";
import { AsyncSection } from "../../../../components/ui/StateView";
import { ProjectTabs } from "../../../../src/features/projects/ProjectTabs";
import { ScorePanel } from "../../../../src/features/report/ScorePanel";
import { useRouteId } from "../../../../src/api/routeParams";

export default function ReportPage() {
  const projectId = useRouteId("projects");
  const query = useApiQuery(["project-score", projectId], `/api/v1/projects/${encodeURIComponent(projectId)}/score`, undefined, projectId.length > 0);
  const score = query.data ? readScore(query.data) : null;

  return (
    <section className="panel">
      <p className="eyebrow">PROJECT · RESURRECTION SCORE</p>
      <h1 className="mono">{projectId}</h1>
      <ProjectTabs projectId={projectId} />
      <AsyncSection loading={query.isLoading} error={query.error ? describeApiError(query.error) : null} empty={null}>
        {score === null ? (
          <p className="muted">API 未返回 resurrection-score 实例，因此没有总分可显示（前端不会计算评分）。</p>
        ) : (
          <ScorePanel score={score} />
        )}
      </AsyncSection>
    </section>
  );
}
