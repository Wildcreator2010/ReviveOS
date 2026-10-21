"use client";

import { useApiQuery } from "../../../../src/api/useApi";
import { describeApiError } from "../../../../src/api/useApi";
import { readCapsules } from "../../../../src/api/readers";
import { AsyncSection } from "../../../../components/ui/StateView";
import { ProjectTabs } from "../../../../src/features/projects/ProjectTabs";
import { CapsuleCard } from "../../../../components/ui/Cards";
import { useRouteId } from "../../../../src/api/routeParams";

export default function ProjectCapsulesPage() {
  const projectId = useRouteId("projects");
  const query = useApiQuery(["project-capsules", projectId], `/api/v1/projects/${encodeURIComponent(projectId)}/capsules`, undefined, projectId.length > 0);
  const capsules = query.data ? readCapsules(query.data) : [];

  return (
    <section className="panel">
      <p className="eyebrow">PROJECT · CAPSULES</p>
      <h1 className="mono">{projectId}</h1>
      <ProjectTabs projectId={projectId} />
      <AsyncSection
        loading={query.isLoading}
        error={query.error ? describeApiError(query.error) : null}
        empty={query.data !== undefined && capsules.length === 0 ? { title: "该项目还没有胶囊", reason: "复生任务尚未产出 .revive 胶囊。", next: null } : null}
      >
        <div className="list">
          {capsules.map((capsule) => (
            <CapsuleCard key={capsule.id} capsule={capsule} />
          ))}
        </div>
      </AsyncSection>
    </section>
  );
}
