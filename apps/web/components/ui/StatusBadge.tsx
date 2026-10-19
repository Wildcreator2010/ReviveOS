import { stateGlyphs, stateLabels, type State } from "../../lib/tokens";

export interface StatusBadgeProps {
  state: State;
  /** Overrides the default label; the glyph is always rendered so colour is never the only carrier. */
  label?: string;
  title?: string;
  /** dashed border = value came from an inference, not a hard fact */
  inferred?: boolean;
}

export function StatusBadge({ state, label, title, inferred = false }: StatusBadgeProps) {
  return (
    <span className={inferred ? "badge badge-plain" : "badge"} data-tone={state} title={title}>
      <span className="dot" aria-hidden="true" />
      <span aria-hidden="true">{stateGlyphs[state]}</span>
      <span>{label ?? stateLabels[state]}</span>
    </span>
  );
}
