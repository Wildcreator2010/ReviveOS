"use client";

export interface MetricMeterProps {
  label: string;
  /** Raw API value. Never recomputed or rounded for display. */
  value: number | null;
  max?: number;
  hint?: string;
  toneState?: "alive" | "partial" | "dead" | "running" | "neutral";
  thin?: boolean;
}

export function MetricMeter({ label, value, max = 100, hint, toneState = "neutral", thin = false }: MetricMeterProps) {
  const clamped = value === null ? 0 : Math.max(0, Math.min(value, max));
  const percent = max > 0 ? (clamped / max) * 100 : 0;
  const display = value === null ? "未知" : String(value);
  return (
    <div className="meter" data-tone={toneState}>
      <span className="muted" title={hint}>{label}</span>
      <div className={`meter-track${thin ? " thin-track" : ""}`} role="meter" aria-valuenow={value ?? undefined} aria-valuemin={0} aria-valuemax={max} aria-label={label} aria-valuetext={display}>
        <div className="meter-fill" style={{ width: `${percent}%` }} />
      </div>
      <span className="meter-value">{display}</span>
    </div>
  );
}

export function toneForConfidence(value: number | null): "alive" | "partial" | "dead" | "neutral" {
  if (value === null) return "neutral";
  if (value >= 0.7) return "alive";
  if (value >= 0.4) return "partial";
  return "dead";
}
