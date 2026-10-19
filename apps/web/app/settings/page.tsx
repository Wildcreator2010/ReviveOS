"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiBaseUrl, apiDelete, apiGet, apiPost, setApiBaseUrl } from "../../src/api/client";
import { asRecord, pickNum, str } from "../../src/api/domain";
import { readApiKeys } from "../../src/api/readers";
import { describeApiError } from "../../src/api/useApi";
import { AsyncSection, OfflineState } from "../../components/ui/StateView";
import { Tile, formatTimestamp } from "../../components/ui/Cards";
import { desktopBridge, useDesktopSettings } from "../../src/desktop/bridge";

function ApiEndpointField() {
  const desktop = useDesktopSettings();
  const [draft, setDraft] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const value = draft ?? desktop.apiBaseUrl ?? apiBaseUrl();

  async function save() {
    const next = (draft ?? value).trim();
    if (next.length === 0) return;
    if (desktop.available) {
      await desktop.setApiBaseUrl(next);
    } else {
      setApiBaseUrl(next);
      try {
        window.localStorage.setItem("revive.apiBaseUrl", next);
      } catch {
        /* storage unavailable: the session override still applies */
      }
    }
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <div className="stack">
      <label className="field" style={{ maxWidth: 520 }}>
        控制面地址（API base URL）
        <input type="url" value={value} onChange={(event) => setDraft(event.target.value)} placeholder="http://127.0.0.1:8000" />
      </label>
      <div className="row">
        <button type="button" className="btn btn-primary" onClick={() => void save()} disabled={value.trim().length === 0}>
          保存
        </button>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => {
            setDraft(null);
            setApiBaseUrl(null);
            if (desktop.available) void desktop.setApiBaseUrl("");
          }}
        >
          恢复默认（http://127.0.0.1:8000）
        </button>
        {saved ? <span className="ok small">已保存</span> : null}
      </div>
      <p className="muted small">
        {desktop.available
          ? "桌面版：地址写入本地 userData 配置文件并由 Electron 主进程持久化，重启后生效（当前窗口立即生效）。"
          : "浏览器版：地址仅保存在本机 localStorage，跨设备不同步。桌面版会把该地址交给 Electron 主进程持久化。"}
      </p>
    </div>
  );
}

function ApiKeysSection() {
  const queryClient = useQueryClient();
  const keys = useQuery({ queryKey: ["api-keys"], queryFn: () => apiGet<unknown>("/api/v1/auth/api-keys") });
  const [label, setLabel] = useState("");
  const [plaintext, setPlaintext] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => apiPost<unknown>("/api/v1/auth/api-keys", { label: label.trim().length > 0 ? label.trim() : null }),
    onSuccess: (payload) => {
      const secret = str(payload) ?? str(asRecord(payload)?.key) ?? str(asRecord(payload)?.plaintext);
      setPlaintext(secret);
      setLabel("");
      void queryClient.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => apiDelete<unknown>(`/api/v1/auth/api-keys/${encodeURIComponent(id)}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["api-keys"] }),
  });

  const parsed = keys.data ? readApiKeys(keys.data) : [];
  const createError = create.error instanceof ApiError ? create.error.message : create.error ? String(create.error) : null;

  return (
    <div className="stack">
      <div className="row">
        <input type="text" placeholder="密钥备注（可选）" value={label} onChange={(event) => setLabel(event.target.value)} style={{ maxWidth: 280 }} aria-label="密钥备注" />
        <button type="button" className="btn" onClick={() => create.mutate()} disabled={create.isPending}>
          {create.isPending ? "创建中…" : "新建 API Key"}
        </button>
      </div>
      {createError ? <p className="small fatal" role="alert">{createError}</p> : null}
      {plaintext ? (
        <div className="banner banner-partial" role="alert">
          <strong>明文只显示这一次，请立即复制保存</strong>
          <p className="mono small" style={{ margin: "8px 0" }}>
            {plaintext}
          </p>
          <div className="row">
            <button type="button" className="btn" onClick={() => void navigator.clipboard?.writeText(plaintext)}>
              复制
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => setPlaintext(null)}>
              我已保存，隐藏
            </button>
          </div>
        </div>
      ) : null}

      <AsyncSection
        loading={keys.isPending}
        error={keys.error ? describeApiError(keys.error) : null}
        empty={keys.data !== undefined && parsed.length === 0 ? { title: "还没有 API Key", reason: "创建后列表只显示前缀（前 8 位），完整密钥不会再次返回。", next: null } : null}
      >
        <table>
          <thead>
            <tr>
              <th>前缀</th>
              <th>备注</th>
              <th>创建时间</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {parsed.map((key) => (
              <tr key={key.id}>
                <td className="mono">{key.prefix}…</td>
                <td>{key.label ?? "—"}</td>
                <td className="mono small">{formatTimestamp(key.createdAt)}</td>
                <td>
                  <button type="button" className="btn btn-danger small" onClick={() => remove.mutate(key.id)} disabled={remove.isPending}>
                    删除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </AsyncSection>
      <p className="muted small">列表只展示前缀；明文只在创建响应的那一次出现，控制台不做任何本地留存。</p>
    </div>
  );
}

function ProfileSection() {
  const me = useQuery({ queryKey: ["me"], queryFn: () => apiGet<unknown>("/api/v1/me") });
  const record = me.data ? asRecord(me.data) : null;
  return (
    <AsyncSection loading={me.isPending} error={me.error ? describeApiError(me.error) : null} empty={null}>
      <div className="grid-4">
        <Tile label="用户" value={<span className="mono" style={{ fontSize: 14 }}>{str(record?.email) ?? str(record?.id) ?? "未知"}</span>} />
        <Tile label="角色" value={str(record?.role) ?? "未知"} />
        <Tile label="并发任务上限" value={pickNum(record, "quota.max_concurrent_jobs") ?? "未知"} tone="running" hint="来自 API 的配额对象；前端不缓存也不推算。" />
        <Tile label="每日任务上限" value={pickNum(record, "quota.max_jobs_per_day") ?? "未知"} tone="running" />
      </div>
    </AsyncSection>
  );
}

export default function SettingsPage() {
  const desktop = useDesktopSettings();
  const health = useQuery({ queryKey: ["settings-health"], queryFn: () => apiGet<unknown>("/healthz") });

  return (
    <div className="stack">
      <section className="panel">
        <p className="eyebrow">SETTINGS</p>
        <h1>设置</h1>
        {health.isError && describeApiError(health.error).offline ? <OfflineState apiUrl={apiBaseUrl()} detail="健康检查失败" onRetry={() => void health.refetch()} /> : null}
        <ApiEndpointField />
      </section>

      <section className="panel">
        <h2>桌面客户端</h2>
        <div className="grid-3">
          <Tile label="运行环境" value={desktop.available ? "Electron 桌面版" : "浏览器"} tone={desktop.available ? "alive" : "neutral"} />
          <Tile label="版本" value={desktop.version ?? "—"} />
          <Tile label="后端进程" value={desktop.backendStatus ?? "未托管"} tone={desktop.backendStatus === "running" ? "alive" : desktop.backendStatus === "failed" ? "dead" : "neutral"} />
        </div>
        <p className="muted small" style={{ marginTop: 12 }}>
          桌面版会尝试连接本地 http://127.0.0.1:8000；如该地址不可达，可在上方改为远端控制面地址。
          {desktop.available && desktopBridge() ? " 本窗口通过 preload 暴露的受限 IPC 通道读写配置，渲染进程没有 Node 权限。" : ""}
        </p>
      </section>

      <section className="panel">
        <h2>我的资料与配额</h2>
        <ProfileSection />
      </section>

      <section className="panel">
        <h2>API Key</h2>
        <ApiKeysSection />
      </section>

      <section className="panel">
        <h2>安全说明</h2>
        <ul className="muted small">
          <li>access token 只保存在内存；refresh token 由后端下发 httpOnly cookie，前端不写入 localStorage。</li>
          <li>API Key 明文只在创建响应中出现一次，列表只显示前缀。</li>
          <li>控制台不持久化任何密钥到文件或 URL query。</li>
        </ul>
      </section>
    </div>
  );
}
