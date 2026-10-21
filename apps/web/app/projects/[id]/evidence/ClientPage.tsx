"use client";


import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../../../../src/api/client";
import { asRecord, itemsOf, num, str } from "../../../../src/api/domain";
import { describeApiError } from "../../../../src/api/useApi";
import { AsyncSection } from "../../../../components/ui/StateView";
import { ProjectTabs } from "../../../../src/features/projects/ProjectTabs";
import { toneForConfidence } from "../../../../components/ui/MetricMeter";
import { useRouteId } from "../../../../src/api/routeParams";

const SOURCE_KINDS = ["git_history", "manifest_file", "ci_config", "doc", "release_artifact", "inference"] as const;

export default function EvidencePage() {
  const projectId = useRouteId("projects");
  const [sourceKind, setSourceKind] = useState<string>("");
  const query = useQuery({
    queryKey: ["project-evidence", projectId, sourceKind],
    queryFn: () =>
      apiGet<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/evidence`, {
        query: { source_kind: sourceKind || undefined, limit: 100 },
      }),
    enabled: projectId.length > 0,
  });
  const items = query.data
    ? itemsOf(query.data)
        .map((entry) => asRecord(entry))
        .filter((entry): entry is Record<string, unknown> => entry !== null)
    : [];

  return (
    <section className="panel">
      <p className="eyebrow">PROJECT · EVIDENCE</p>
      <h1 className="mono">{projectId}</h1>
      <ProjectTabs projectId={projectId} />

      <div className="row" style={{ marginBottom: 12 }}>
        <label className="field" style={{ maxWidth: 260 }}>
          证据来源
          <select value={sourceKind} onChange={(event) => setSourceKind(event.target.value)}>
            <option value="">全部</option>
            {SOURCE_KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {kind}
              </option>
            ))}
          </select>
        </label>
      </div>

      <AsyncSection
        loading={query.isPending}
        error={query.error ? describeApiError(query.error) : null}
        empty={
          query.data !== undefined && items.length === 0
            ? { title: "没有证据条目", reason: sourceKind ? `该来源（${sourceKind}）下没有记录。` : "控制面返回空数组。", next: null }
            : null
        }
      >
        <table>
          <thead>
            <tr>
              <th>来源</th>
              <th>引用</th>
              <th>置信度</th>
              <th>备注</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, index) => {
              const confidence = num(item.confidence);
              const kind = str(item.source_kind) ?? "未知";
              return (
                <tr key={index} data-tone={toneForConfidence(confidence)}>
                  <td>
                    <span className="tag">{kind}</span>
                    {kind === "inference" ? <span className="tag" style={{ marginLeft: 6 }}>推断</span> : null}
                  </td>
                  <td className="mono small">{str(item.reference) ?? "—"}</td>
                  <td className="mono">{confidence === null ? "未知" : confidence}</td>
                  <td className="small">{str(item.note) ?? "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="muted small" style={{ marginTop: 12 }}>
          证据链只回引用与事实（reference / facts），控制面不暴露仓库源码原文。
        </p>
      </AsyncSection>
    </section>
  );
}
