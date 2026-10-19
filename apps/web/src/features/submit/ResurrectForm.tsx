"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { ApiError, apiBaseUrl, apiPost } from "../../api/client";
import { pickStr, str } from "../../api/domain";
import { readProject } from "../../api/readers";

const GITHUB_RE = /^https:\/\/github\.com\/[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+\/?$/;

type Options = {
  budgetUsd: string;
  timeoutMinutes: string;
  allowOffline: boolean;
};

export function ResurrectForm() {
  const router = useRouter();
  const [repoUrl, setRepoUrl] = useState("");
  const [options, setOptions] = useState<Options>({ budgetUsd: "5", timeoutMinutes: "60", allowOffline: true });
  const [submitting, setSubmitting] = useState(false);
  const [urlError, setUrlError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [existingId, setExistingId] = useState<string | null>(null);
  const [retryAfter, setRetryAfter] = useState<number | null>(null);

  const urlValid = GITHUB_RE.test(repoUrl.trim());

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setFormError(null);
    setExistingId(null);
    setRetryAfter(null);
    if (!urlValid) {
      setUrlError("请输入 https://github.com/owner/repo 形式的公开仓库地址。");
      return;
    }
    setUrlError(null);
    setSubmitting(true);
    try {
      const project = await apiPost<unknown>("/api/v1/projects", { repo_url: repoUrl.trim() });
      const created = readProject(project);
      if (!created) throw new ApiError(500, "internal", { message: "创建项目未返回有效的项目 id。" });
      await resurrect(created.id);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        const id = pickStr(error.details, "existing_id") ?? pickStr(error.details, "detail.existing_id") ?? str(error.details.existing_id);
        setExistingId(id);
        setFormError("项目已存在：直接新建任务或查看历史。");
      } else if (error instanceof ApiError && error.status === 429) {
        setRetryAfter(error.retryAfterSeconds);
        setFormError(error.message);
      } else if (error instanceof ApiError) {
        setFormError(error.message);
      } else {
        setFormError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function resurrect(projectId: string) {
    const job = await apiPost<unknown>(`/api/v1/projects/${encodeURIComponent(projectId)}/resurrect`, {
      budget_usd: Number(options.budgetUsd),
      timeout_seconds: Number(options.timeoutMinutes) * 60,
      allow_offline_analysis: options.allowOffline,
    });
    const jobId = pickStr(job, "job_id") ?? pickStr(job, "id") ?? str((job as { job?: { id?: string } } | null)?.job?.id);
    if (!jobId) throw new ApiError(500, "internal", { message: "resurrect 未返回 job_id。" });
    router.push(`/jobs/${encodeURIComponent(jobId)}`);
  }

  async function resurrectExisting() {
    if (!existingId) return;
    setSubmitting(true);
    setFormError(null);
    try {
      await resurrect(existingId);
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="panel">
      <p className="eyebrow">RESURRECT SUBMISSION</p>
      <h2>提交复生任务</h2>
      <form onSubmit={submit} className="stack" noValidate>
        <label className="field">
          GitHub 仓库地址
          <input
            type="url"
            inputMode="url"
            placeholder="https://github.com/owner/repo"
            value={repoUrl}
            onChange={(event) => setRepoUrl(event.target.value)}
            aria-invalid={urlError !== null}
            aria-describedby={urlError ? "repo-url-error" : undefined}
            disabled={submitting}
            required
          />
        </label>
        {urlError ? (
          <p id="repo-url-error" className="small fatal" role="alert">
            {urlError}
          </p>
        ) : null}

        <div className="grid-3">
          <label className="field">
            预算上限（USD）
            <input type="number" min="0" step="1" value={options.budgetUsd} onChange={(event) => setOptions({ ...options, budgetUsd: event.target.value })} disabled={submitting} />
          </label>
          <label className="field">
            超时（分钟）
            <input type="number" min="1" step="1" value={options.timeoutMinutes} onChange={(event) => setOptions({ ...options, timeoutMinutes: event.target.value })} disabled={submitting} />
          </label>
          <label className="check" style={{ alignSelf: "end", paddingBottom: 8 }}>
            <input type="checkbox" checked={options.allowOffline} onChange={(event) => setOptions({ ...options, allowOffline: event.target.checked })} disabled={submitting} />
            允许离线分析
          </label>
        </div>

        <div className="row">
          <button type="submit" className="btn btn-primary" disabled={submitting || !urlValid}>
            {submitting ? "提交中…" : "提交复生"}
          </button>
          <span className="muted small mono" title="控制面地址">
            API {apiBaseUrl()}
          </span>
        </div>

        {formError ? (
          <div className="banner banner-partial" role="alert">
            <strong>{formError}</strong>
            {retryAfter !== null ? (
              <p className="small" style={{ margin: "6px 0 0" }}>
                配额恢复倒计时：{retryAfter} 秒。
              </p>
            ) : null}
            {existingId ? (
              <div className="row" style={{ marginTop: 8 }}>
                <button type="button" className="btn" onClick={() => void resurrectExisting()} disabled={submitting}>
                  为该项目新建任务
                </button>
                <a className="btn btn-ghost" href={`/projects/${encodeURIComponent(existingId)}`}>
                  查看项目历史
                </a>
              </div>
            ) : null}
          </div>
        ) : null}
      </form>
    </section>
  );
}
