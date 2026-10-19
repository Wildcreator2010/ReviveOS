"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { StatusBadge } from "./StatusBadge";
import { stateGlyphs } from "../../lib/tokens";
import { CAPSULE_STATUS_LABELS, JOB_STATUS_LABELS, toneForCapsuleStatus, toneForJobStatus, type CapsuleStatus, type JobStatus } from "../../src/api/domain-types";
import type { CapsuleView, JobSummary, PatchView, ProjectSummary } from "../../src/api/readers";

export function formatTimestamp(value: string | null): string {
  if (!value) return "—";
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return value;
  return new Date(parsed).toISOString().replace("T", " ").slice(0, 19) + "Z";
}

export function JobStatusBadge({ status, label }: { status: JobStatus; label?: string }) {
  return <StatusBadge state={toneForJobStatus(status)} label={label ?? JOB_STATUS_LABELS[status]} />;
}

export function CapsuleStatusBadge({ status }: { status: CapsuleStatus }) {
  return <StatusBadge state={toneForCapsuleStatus(status)} label={CAPSULE_STATUS_LABELS[status]} />;
}

export function ProjectCard({ project }: { project: ProjectSummary }) {
  return (
    <article className="list-item" data-tone={project.status === "alive" ? "alive" : project.status === "dead" ? "dead" : "neutral"}>
      <div className="spread">
        <div>
          <h3 style={{ margin: 0 }}>
            <Link href={`/projects/${encodeURIComponent(project.id)}`}>{project.repo ?? project.repoUrl ?? project.id}</Link>
          </h3>
          <p className="muted small mono" style={{ margin: "4px 0 0" }}>
            {project.id}
            {project.commit ? ` · ${project.commit.slice(0, 12)}` : ""}
          </p>
        </div>
        <div className="row">
          {project.latestScore !== null ? <span className="tag">score {project.latestScore}</span> : <span className="tag">无评分</span>}
          {project.status ? <span className="tag">{project.status}</span> : null}
        </div>
      </div>
      <p className="muted small" style={{ marginBottom: 0 }}>
        最近更新 {formatTimestamp(project.updatedAt)}
      </p>
    </article>
  );
}

export function JobRow({ job }: { job: JobSummary }) {
  return (
    <tr>
      <td>
        <Link href={`/jobs/${encodeURIComponent(job.id)}`} className="mono">
          {job.id}
        </Link>
      </td>
      <td>{job.projectId ? <Link href={`/projects/${encodeURIComponent(job.projectId)}`} className="mono">{job.projectId}</Link> : "—"}</td>
      <td>
        <JobStatusBadge status={job.status} label={job.rawStatus ?? undefined} />
      </td>
      <td className="mono small">{formatTimestamp(job.createdAt)}</td>
      <td className="mono small">{formatTimestamp(job.finishedAt)}</td>
      <td className="small">{job.errorCode ?? "—"}</td>
    </tr>
  );
}

export function CapsuleCard({ capsule }: { capsule: CapsuleView }) {
  return (
    <article className="list-item" data-tone={capsule.status === "unknown" ? "neutral" : capsule.status}>
      <div className="spread">
        <div>
          <h3 style={{ margin: 0 }}>
            <Link href={`/capsules/${encodeURIComponent(capsule.id)}`} className="mono">
              {capsule.id}
            </Link>
          </h3>
          <p className="muted small mono" style={{ margin: "4px 0 0" }}>
            {capsule.format ?? "格式未知"} · {capsule.repo ?? "仓库未知"} · {capsule.commit ? capsule.commit.slice(0, 12) : "commit 未知"}
          </p>
        </div>
        <CapsuleStatusBadge status={capsule.status} />
      </div>
      <div className="row small muted" style={{ marginTop: 6 }}>
        {capsule.scoreTotal !== null ? <span className="tag">score {capsule.scoreTotal}</span> : <span className="tag">无评分</span>}
        {capsule.patchCount !== null ? <span className="tag">{capsule.patchCount} 个补丁</span> : null}
        {capsule.sbomDigest ? <span className="tag mono">sbom {capsule.sbomDigest.slice(0, 12)}</span> : null}
      </div>
      {capsule.downloadUrl ? (
        <p style={{ marginBottom: 0, marginTop: 8 }}>
          <a className="btn btn-ghost" href={capsule.downloadUrl}>
            下载胶囊
          </a>
        </p>
      ) : (
        <p className="muted small" style={{ marginBottom: 0, marginTop: 8 }}>
          下载链接由 API 的 presigned URL 提供；前端不拼接签名地址。
        </p>
      )}
    </article>
  );
}

export function PatchCard({ patch }: { patch: PatchView }) {
  const tone = patch.refused || patch.rolledBack ? "partial" : patch.result === "failed" ? "dead" : "neutral";
  return (
    <article className={`list-item${patch.rolledBack ? " strike" : ""}`} data-tone={tone}>
      <div className="spread">
        <h3 style={{ margin: 0 }} className="mono">
          #{patch.index ?? "?"} {patch.summary ?? patch.id}
        </h3>
        <div className="row">
          {patch.risk ? <span className="tag">风险 {patch.risk}</span> : null}
          {patch.result ? <span className="tag">结果 {patch.result}</span> : null}
          {patch.rolledBack ? <StatusBadge state="partial" label="已回滚" /> : null}
          {patch.refused ? <StatusBadge state="dead" label="被拒绝" /> : null}
        </div>
      </div>
      {patch.rationale ? <p style={{ margin: "8px 0 0" }}>{patch.rationale}</p> : <p className="muted small">API 未提供 rationale。</p>}
      {patch.signature ? (
        <p className="muted small mono" style={{ margin: "6px 0 0" }}>
          触发签名：{patch.signature}
        </p>
      ) : null}
      {patch.refusedReason ? (
        <p className="small warn" style={{ margin: "6px 0 0" }}>
          拒绝原因：{patch.refusedReason}
        </p>
      ) : null}
      {patch.files.length > 0 ? (
        <p className="muted small mono" style={{ margin: "6px 0 0" }}>
          {patch.files.join(", ")}
        </p>
      ) : null}
    </article>
  );
}

export function Tile({ label, value, tone, hint }: { label: string; value: ReactNode; tone?: "alive" | "partial" | "dead" | "running" | "neutral"; hint?: string }) {
  return (
    <div className="tile" data-tone={tone ?? "neutral"} title={hint}>
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}</div>
    </div>
  );
}

export { stateGlyphs };
