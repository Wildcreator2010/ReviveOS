"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { apiGet } from "../../src/api/client";
import { readCapsules } from "../../src/api/readers";
import { describeApiError } from "../../src/api/useApi";
import { AsyncSection } from "../../components/ui/StateView";
import { CapsuleCard } from "../../components/ui/Cards";

export default function CapsulesPage() {
  const [projectId, setProjectId] = useState("");
  const query = useQuery({
    queryKey: ["capsules", projectId],
    queryFn: () => apiGet<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/capsules`),
    enabled: projectId.trim().length > 0,
  });
  const items = query.data ? readCapsules(query.data) : [];

  return (
    <div className="stack">
      <section className="panel">
        <p className="eyebrow">CAPSULES</p>
        <h1>胶囊</h1>
        <p className="muted">
          胶囊列表挂在项目下（GET /api/v1/projects/&#123;id&#125;/capsules）。没有项目级聚合端点，因此这里需要显式输入项目 id，
          前端不会伪造一个「全部胶囊」列表。
        </p>
        <div className="row" style={{ marginTop: 12 }}>
          <input
            type="text"
            placeholder="项目 id（rev_project_…）"
            value={projectId}
            onChange={(event) => setProjectId(event.target.value)}
            style={{ maxWidth: 420 }}
            aria-label="项目 id"
          />
          <button type="button" className="btn" onClick={() => void query.refetch()} disabled={projectId.trim().length === 0 || query.isFetching}>
            查询
          </button>
        </div>
      </section>

      <section className="panel">
        {projectId.trim().length === 0 ? (
          <p className="muted">输入项目 id 后显示该项目产出的胶囊、manifest 摘要与 presigned 下载入口。</p>
        ) : (
          <AsyncSection
            loading={query.isPending}
            error={query.error ? describeApiError(query.error) : null}
            empty={query.data && items.length === 0 ? { title: "该项目还没有胶囊", reason: "复生任务尚未产出 .revive 胶囊，或控制面返回空数组。", next: null } : null}
          >
            <div className="list">
              {items.map((capsule) => (
                <CapsuleCard key={capsule.id} capsule={capsule} />
              ))}
            </div>
          </AsyncSection>
        )}
      </section>
    </div>
  );
}
