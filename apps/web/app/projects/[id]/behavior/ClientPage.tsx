"use client";


import { useApiQuery } from "../../../../src/api/useApi";
import { describeApiError } from "../../../../src/api/useApi";
import { readBehavior } from "../../../../src/api/readers";
import { AsyncSection } from "../../../../components/ui/StateView";
import { ProjectTabs } from "../../../../src/features/projects/ProjectTabs";
import { BehaviorPanel } from "../../../../src/features/report/BehaviorPanel";
import { useRouteId } from "../../../../src/api/routeParams";

export default function BehaviorPage() {
  const projectId = useRouteId("projects");
  const query = useApiQuery(["project-behavior", projectId], `/api/v1/projects/${encodeURIComponent(projectId)}/behavior`, undefined, projectId.length > 0);
  const behavior = query.data ? readBehavior(query.data) : null;

  return (
    <section className="panel">
      <p className="eyebrow">PROJECT · BEHAVIOR</p>
      <h1 className="mono">{projectId}</h1>
      <ProjectTabs projectId={projectId} />
      <AsyncSection loading={query.isLoading} error={query.error ? describeApiError(query.error) : null} empty={null}>
        {behavior === null ? <p className="muted">API 未返回行为报告。</p> : <BehaviorPanel behavior={behavior} />}
      </AsyncSection>
    </section>
  );
}
