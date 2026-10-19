/**
 * Single source of truth for status colour semantics.
 * The CSS variables live in app/globals.css; nothing else may hard-code a hue.
 */
export const stateTokens = {
  alive: "var(--state-alive)",
  partial: "var(--state-partial)",
  dead: "var(--state-dead)",
  running: "var(--state-running)",
  neutral: "var(--state-neutral)",
} as const;

export type State = keyof typeof stateTokens;

/** Non-colour carrier so status is never communicated by hue alone (a11y). */
export const stateGlyphs: Record<State, string> = {
  alive: "●",
  partial: "◐",
  dead: "○",
  running: "▶",
  neutral: "·",
};

export const stateLabels: Record<State, string> = {
  alive: "ALIVE",
  partial: "PARTIAL",
  dead: "DEAD",
  running: "进行中",
  neutral: "未知",
};
