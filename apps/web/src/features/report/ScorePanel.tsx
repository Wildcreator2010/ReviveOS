"use client";

import { MetricMeter } from "../../../components/ui/MetricMeter";
import { StatusBadge } from "../../../components/ui/StatusBadge";
import type { ScoreView } from "../../../src/api/readers";
import type { State } from "../../../lib/tokens";

/** Judgement mapping is documented in the capsule contract (T-CAP-01); the console only mirrors it. */
export function judgementForScore(total: number | null): { state: State; label: string; reason: string } {
  if (total === null) return { state: "neutral", label: "无判定", reason: "API 未返回 total。" };
  if (total >= 80) return { state: "alive", label: "ALIVE", reason: "total ≥ 80" };
  if (total >= 50) return { state: "partial", label: "PARTIAL", reason: "50 ≤ total < 80" };
  return { state: "dead", label: "DEAD", reason: "total < 50" };
}

export function ScorePanel({ score }: { score: ScoreView }) {
  const judgement = judgementForScore(score.total);
  const degraders = score.components.filter((component) => component.value !== null && component.value < 80);

  return (
    <div className="stack">
      <div className="grid-2">
        <div className="tile" data-tone={judgement.state}>
          <div className="tile-label">Resurrection Score · total</div>
          <div className="tile-value" style={{ fontSize: 44 }}>{score.total === null ? "—" : score.total}</div>
          <div className="row" style={{ marginTop: 8 }}>
            <StatusBadge state={judgement.state} label={judgement.label} title={judgement.reason} />
            <span className="muted small">判定阈值 {judgement.reason}（前端只做阈值映射，不做评分计算）</span>
          </div>
        </div>
        <div className="tile">
          <div className="tile-label">分项（权重来自 resurrection-score schema）</div>
          <div className="stack" style={{ marginTop: 10 }}>
            {score.components.map((component) => (
              <MetricMeter
                key={component.key}
                label={`${component.label}${component.weight === null ? "" : ` (${component.weight})`}`}
                value={component.value}
                toneState={component.value === null ? "neutral" : component.value >= 80 ? "alive" : component.value >= 50 ? "partial" : "dead"}
                hint={`权重 ${component.weight ?? "未知"}；数值直接来自 API`}
              />
            ))}
          </div>
        </div>
      </div>

      <div className="banner">
        <strong>触发降级的分量</strong>
        <p className="small" style={{ margin: "6px 0 0" }}>
          {degraders.length === 0
            ? "所有分项均 ≥ 80，没有额外降级触发项。"
            : degraders.map((component) => `${component.label}=${component.value}`).join(" · ")}
        </p>
      </div>

      <details className="raw">
        <summary>原始评分 JSON（API 原样）</summary>
        <pre className="payload">{JSON.stringify(score.raw, null, 2)}</pre>
      </details>
    </div>
  );
}
