"use client";

import { useMemo } from "react";

export interface DiffViewProps {
  /** Unified diff text straight from the API. Never re-generated on the client. */
  text: string;
  /** Hard cap of rendered lines (long diffs render a tail window with an explicit notice). */
  maxLines?: number;
}

interface DiffLine {
  kind: "add" | "del" | "hunk" | "meta" | "context";
  text: string;
}

export function parseUnifiedDiff(text: string): DiffLine[] {
  return text.split(/\r?\n/).map((line) => {
    if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff ") || line.startsWith("index ")) {
      return { kind: "meta", text: line };
    }
    if (line.startsWith("@@")) return { kind: "hunk", text: line };
    if (line.startsWith("+")) return { kind: "add", text: line };
    if (line.startsWith("-")) return { kind: "del", text: line };
    return { kind: "context", text: line };
  });
}

/**
 * Self-drawn unified diff (no heavyweight editor dependency). Renders a bounded
 * window so a 10k-line diff cannot lock the renderer, and says what it hid.
 */
export function DiffView({ text, maxLines = 2000 }: DiffViewProps) {
  const parsed = useMemo(() => parseUnifiedDiff(text), [text]);
  const shown = parsed.length > maxLines ? parsed.slice(0, maxLines) : parsed;
  const hidden = parsed.length - shown.length;
  return (
    <div>
      <div className="diff">
        {shown.map((line, index) => (
          <div key={index} className={`diff-line diff-${line.kind}`}>
            <span className="ln">{index + 1}</span>
            <span className="code">{line.text.length > 0 ? line.text : " "}</span>
          </div>
        ))}
      </div>
      {hidden > 0 ? (
        <p className="muted small">
          仅渲染前 {maxLines} 行，另有 {hidden} 行未显示（如需完整内容请下载补丁产物）。
        </p>
      ) : null}
    </div>
  );
}
