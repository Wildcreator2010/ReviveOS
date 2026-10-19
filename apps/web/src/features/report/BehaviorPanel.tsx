"use client";

import { MetricMeter } from "../../../components/ui/MetricMeter";
import { StatusBadge } from "../../../components/ui/StatusBadge";
import type { BehaviorView } from "../../../src/api/readers";

export function BehaviorPanel({ behavior }: { behavior: BehaviorView }) {
  if (!behavior.available) {
    return (
      <div className="banner banner-partial" role="status">
        <div className="row">
          <StatusBadge state="partial" label="无行为基线" />
          <strong>兼容率不可用</strong>
        </div>
        <p className="small" style={{ margin: "8px 0 0" }}>
          {behavior.reason ?? "API 返回的 compatibility 为 null：该仓库在复生前没有可执行的测试或入口，无法建立行为基线。"}
        </p>
        <p className="muted small" style={{ margin: "6px 0 0" }}>
          这是诚实结果，不是 0 分：控制台不会把 null 渲染成 0，也不会把缺失的用例补成通过。
        </p>
      </div>
    );
  }

  const compatibility = behavior.compatibility ?? 0;

  return (
    <div className="stack">
      <div className="row">
        <MetricMeter
          label="行为兼容率"
          value={compatibility}
          toneState={compatibility >= 95 ? "alive" : compatibility >= 70 ? "partial" : "dead"}
          hint="直接显示 API 的 compatibility，前端不重算。"
        />
      </div>

      {behavior.cases.length === 0 ? (
        <p className="muted small">API 未返回逐用例明细。</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>用例</th>
              <th>状态</th>
              <th>期望</th>
              <th>实际</th>
              <th>容差 / 漂移</th>
            </tr>
          </thead>
          <tbody>
            {behavior.cases.map((testCase, index) => (
              <tr key={`${testCase.name}-${index}`} data-tone={testCase.status === "pass" ? "alive" : testCase.status === "fail" ? "dead" : "neutral"}>
                <td className="mono small">{testCase.name}</td>
                <td>{testCase.status ?? "未知"}</td>
                <td className="mono small">{testCase.expected ?? "—"}</td>
                <td className="mono small">{testCase.actual ?? "—"}</td>
                <td className="mono small">
                  {testCase.epsilon !== null && testCase.expected !== null && testCase.actual !== null
                    ? `|${testCase.expected} - ${testCase.actual}| ≤ ${testCase.epsilon}`
                    : testCase.drift ?? (testCase.epsilon !== null ? `eps=${testCase.epsilon}` : "—")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <p className="muted small" aria-live="polite">
        共 {behavior.cases.length} 条用例明细（来自 API）。
      </p>
    </div>
  );
}
