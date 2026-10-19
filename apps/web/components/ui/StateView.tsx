"use client";

import type { ReactNode } from "react";

export function LoadingState({ label = "正在读取 API…", rows = 3 }: { label?: string; rows?: number }) {
  return (
    <div className="stack" aria-busy="true" aria-live="polite">
      <p className="muted small">{label}</p>
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="skeleton" />
      ))}
    </div>
  );
}

export interface EmptyStateProps {
  title: string;
  /** Why the view is empty — the API is authoritative, so the UI states the reason instead of inventing data. */
  reason: string;
  next?: ReactNode;
}

export function EmptyState({ title, reason, next }: EmptyStateProps) {
  return (
    <div className="empty" role="status">
      <p>
        <strong>{title}</strong>
      </p>
      <p>{reason}</p>
      {next ? <div className="row">{next}</div> : null}
    </div>
  );
}

/**
 * Backend unreachable / offline state. Distinguishes "no data yet" from
 * "cannot reach the control plane", which is the desktop app's default cold start.
 */
export function OfflineState({ apiUrl, detail, onRetry }: { apiUrl: string; detail?: string | null; onRetry?: () => void }) {
  return (
    <div className="banner banner-dead" role="alert">
      <p>
        <strong>离线：无法连接控制面</strong>
      </p>
      <p className="small mono">目标地址：{apiUrl}</p>
      {detail ? <p className="small mono">{detail}</p> : null}
      <p className="small">请在「设置」中确认 API 地址，或启动本地后端（默认 http://127.0.0.1:8000）。本页不会显示任何伪造数据。</p>
      {onRetry ? (
        <button type="button" className="btn" onClick={onRetry}>
          重试
        </button>
      ) : null}
    </div>
  );
}

export function ErrorState({ code, message, onRetry }: { code: string; message: string; onRetry?: () => void }) {
  return (
    <div className="banner banner-partial" role="alert">
      <p>
        <strong>接口返回错误</strong>
      </p>
      <p className="small mono">
        {code} · {message}
      </p>
      {onRetry ? (
        <button type="button" className="btn" onClick={onRetry}>
          重试
        </button>
      ) : null}
    </div>
  );
}

/** Standard three-way renderer: loading / error / empty / content. */
export function AsyncSection({
  loading,
  error,
  empty,
  children,
}: {
  loading: boolean;
  error: { code: string; message: string; offline: boolean } | null;
  empty: EmptyStateProps | null;
  children: ReactNode;
}) {
  if (loading) return <LoadingState />;
  if (error) {
    return error.offline ? <OfflineState apiUrl={error.message} detail={error.code} /> : <ErrorState code={error.code} message={error.message} />;
  }
  if (empty) return <EmptyState {...empty} />;
  return <>{children}</>;
}
