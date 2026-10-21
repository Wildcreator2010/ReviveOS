"use client";


import { useApiQuery } from "../../../../src/api/useApi";
import { describeApiError } from "../../../../src/api/useApi";
import { readGenome } from "../../../../src/api/readers";
import { AsyncSection } from "../../../../components/ui/StateView";
import { ProjectTabs } from "../../../../src/features/projects/ProjectTabs";
import { GenomePanel } from "../../../../src/features/genome/GenomePanel";
import { useRouteId } from "../../../../src/api/routeParams";

export default function GenomePage() {
  const projectId = useRouteId("projects");
  const query = useApiQuery(["project-genome", projectId], `/api/v1/projects/${encodeURIComponent(projectId)}/genome`, undefined, projectId.length > 0);
  const genome = query.data ? readGenome(query.data) : null;

  return (
    <section className="panel">
      <p className="eyebrow">PROJECT · GENOME + EVIDENCE</p>
      <h1 className="mono">{projectId}</h1>
      <ProjectTabs projectId={projectId} />
      <AsyncSection loading={query.isLoading} error={query.error ? describeApiError(query.error) : null} empty={null}>
        {genome === null ? (
          <p className="muted">API 返回的 genome 不符合契约（缺少可读字段），未渲染任何推测内容。</p>
        ) : (
          <>
            <div className="row" style={{ marginBottom: 12 }}>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => void navigator.clipboard?.writeText(JSON.stringify(genome.raw, null, 2))}
              >
                复制 genome.json
              </button>
              <span className="muted small">原始 JSON 直接来自 API 响应。</span>
            </div>
            <GenomePanel genome={genome} />
          </>
        )}
      </AsyncSection>
    </section>
  );
}
