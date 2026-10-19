"use client";

import { useMemo, useState } from "react";
import { MetricMeter, toneForConfidence } from "../../../components/ui/MetricMeter";
import { StatusBadge } from "../../../components/ui/StatusBadge";
import type { GenomeView, EvidenceItem } from "../../../src/api/readers";

const SOURCE_LABELS: Record<string, string> = {
  git_history: "git 历史",
  manifest_file: "清单文件",
  ci_config: "CI 配置",
  doc: "文档",
  release_artifact: "发布产物",
  inference: "推断",
};

function EvidenceRow({ item }: { item: EvidenceItem }) {
  const inferred = item.sourceKind === "inference";
  return (
    <li
      className="list-item"
      data-tone={toneForConfidence(item.confidence)}
      style={inferred ? { borderStyle: "dashed" } : undefined}
    >
      <div className="row">
        <span className="tag">{SOURCE_LABELS[item.sourceKind] ?? item.sourceKind}</span>
        <span className="mono small">{item.reference}</span>
        {item.confidence !== null ? (
          <span className="small muted">confidence {item.confidence}</span>
        ) : (
          <span className="small muted">confidence 未知</span>
        )}
      </div>
      {item.note ? <p className="small" style={{ margin: "6px 0 0" }}>{item.note}</p> : null}
    </li>
  );
}

export function GenomePanel({ genome }: { genome: GenomeView }) {
  const [open, setOpen] = useState<string | null>(null);
  const lowConfidence = useMemo(() => genome.fields.filter((field) => field.confidence !== null && field.confidence < 0.7), [genome.fields]);

  return (
    <div className="stack">
      {lowConfidence.length > 0 ? (
        <div className="banner banner-partial" role="status">
          低置信项 {lowConfidence.length} 个待确认：
          <span className="mono small"> {lowConfidence.map((field) => field.label).join("、")}</span>
        </div>
      ) : null}

      <div className="row">
        <MetricMeter label="整体置信度" value={genome.overallConfidence === null ? null : Math.round(genome.overallConfidence * 100)} toneState={toneForConfidence(genome.overallConfidence)} hint="overall_confidence × 100，仅展示。" />
      </div>

      <div className="list">
        {genome.fields.map((field) => (
          <div className="list-item" key={field.key} data-tone={toneForConfidence(field.confidence)}>
            <div className="spread">
              <div>
                <h3 style={{ margin: 0 }}>{field.label}</h3>
                <p className="mono small" style={{ margin: "4px 0 0" }}>
                  {field.version ?? field.image ?? "API 未提供版本"}
                </p>
              </div>
              <div className="row">
                {field.confidence !== null ? <StatusBadge state={toneForConfidence(field.confidence)} label={`信心 ${field.confidence}`} /> : <span className="tag">无置信度</span>}
                {field.fromLlm ? <span className="tag" title="该字段由模型补强，必须与规则引擎结论区分">AI 补强</span> : null}
              </div>
            </div>
            <button type="button" className="btn btn-ghost small" style={{ marginTop: 8 }} onClick={() => setOpen(open === field.key ? null : field.key)} aria-expanded={open === field.key}>
              {open === field.key ? "收起证据" : `查看证据（${field.evidence.length}）`}
            </button>
            {open === field.key ? (
              field.evidence.length > 0 ? (
                <ul className="list" style={{ listStyle: "none", padding: 0, marginTop: 8 }}>
                  {field.evidence.map((item, index) => (
                    <EvidenceRow key={`${field.key}-${index}`} item={item} />
                  ))}
                </ul>
              ) : (
                <p className="muted small" style={{ marginTop: 8 }}>
                  API 未返回该字段的证据条目。
                </p>
              )
            ) : null}
          </div>
        ))}
      </div>

      {genome.dependencies.length > 0 ? (
        <div>
          <h2>依赖</h2>
          <ul className="list" style={{ listStyle: "none", padding: 0 }}>
            {genome.dependencies.map((item, index) => (
              <EvidenceRow key={`dep-${index}`} item={item} />
            ))}
          </ul>
        </div>
      ) : (
        <p className="muted small">API 未返回依赖列表。</p>
      )}
    </div>
  );
}
