"use client";


import { useApiQuery } from "../../../../src/api/useApi";
import { describeApiError } from "../../../../src/api/useApi";
import { readPatches } from "../../../../src/api/readers";
import { AsyncSection } from "../../../../components/ui/StateView";
import { ProjectTabs } from "../../../../src/features/projects/ProjectTabs";
import { PatchCard } from "../../../../components/ui/Cards";
import { DiffView } from "../../../../components/ui/DiffView";
import { useRouteId } from "../../../../src/api/routeParams";

export default function PatchesPage() {
  const projectId = useRouteId("projects");
  const query = useApiQuery(["project-patches", projectId], `/api/v1/projects/${encodeURIComponent(projectId)}/patches`, undefined, projectId.length > 0);
  const patches = query.data ? readPatches(query.data) : [];

  return (
    <section className="panel">
      <p className="eyebrow">PROJECT · PATCHES</p>
      <h1 className="mono">{projectId}</h1>
      <ProjectTabs projectId={projectId} />
      <p className="muted small">
        复生过程只在本任务的沙箱副本里改代码；控制台不提供「一键合并回上游」，这是产品原则。
      </p>
      <AsyncSection
        loading={query.isLoading}
        error={query.error ? describeApiError(query.error) : null}
        empty={query.data !== undefined && patches.length === 0 ? { title: "还没有补丁记录", reason: "控制面返回空数组：任务尚未进入修复阶段，或没有产生补丁。", next: null } : null}
      >
        <div className="stack">
          {patches.map((patch) => (
            <div key={patch.id}>
              <PatchCard patch={patch} />
              {patch.diff ? (
                <div style={{ marginTop: 8 }}>
                  <DiffView text={patch.diff} />
                </div>
              ) : (
                <p className="muted small">该补丁没有 diff 文本（API 未提供 unified diff）。</p>
              )}
            </div>
          ))}
        </div>
      </AsyncSection>
    </section>
  );
}
