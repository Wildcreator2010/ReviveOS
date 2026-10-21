"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ApiError, apiGet, request } from "../../api/client";

interface LlmSettings {
  provider: string;
  base_url: string;
  model: string;
  reasoning_effort: string | null;
  api_key_set: boolean;
  api_key_hint: string | null;
  source: string;
}

interface LlmTest {
  ok: boolean;
  provider: string;
  model: string;
  latency_ms: number | null;
  detail: string | null;
}

const PROVIDERS = [
  { value: "fake", label: "fake（本地演示，不联网）" },
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "custom", label: "Custom（OpenAI 兼容网关）" },
] as const;

export function ModelProviderSection() {
  const query = useQuery({
    queryKey: ["llm-settings"],
    queryFn: () => apiGet<LlmSettings>("/api/v1/admin/llm"),
    retry: false,
  });
  const [provider, setProvider] = useState("fake");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [reasoning, setReasoning] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [test, setTest] = useState<LlmTest | null>(null);

  useEffect(() => {
    const data = query.data;
    if (!data) return;
    setProvider(data.provider || "fake");
    setBaseUrl(data.base_url || "");
    setModel(data.model || "");
    setReasoning(data.reasoning_effort || "");
  }, [query.data]);

  if (query.isError) {
    const forbidden = query.error instanceof ApiError && query.error.status === 403;
    return (
      <section className="panel">
        <p className="eyebrow">MODEL GATEWAY</p>
        <h2>模型提供方</h2>
        <p className="muted small">{forbidden ? "仅管理员可以查看和修改模型配置。" : "无法读取模型配置。"}</p>
      </section>
    );
  }

  async function save() {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const data = await request<LlmSettings>("/api/v1/admin/llm", {
        method: "PUT",
        body: {
          provider,
          base_url: baseUrl.trim(),
          model: model.trim(),
          api_key: apiKey.trim() || undefined,
          clear_api_key: clearKey,
          reasoning_effort: reasoning || null,
        },
      });
      setApiKey("");
      setClearKey(false);
      setMessage(`已保存：${data.provider}${data.model ? ` / ${data.model}` : ""}`);
      void query.refetch();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSaving(false);
    }
  }

  async function runTest() {
    setTesting(true);
    setTest(null);
    setError(null);
    try {
      setTest(await request<LlmTest>("/api/v1/admin/llm/test", { method: "POST" }));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : caught instanceof Error ? caught.message : String(caught));
    } finally {
      setTesting(false);
    }
  }

  const data = query.data;
  const customNeedsBase = provider === "custom";
  const needsConnection = provider !== "fake";

  return (
    <section className="panel">
      <p className="eyebrow">MODEL GATEWAY</p>
      <div className="spread">
        <h2>模型提供方</h2>
        <span className="badge badge-plain" data-tone={data?.api_key_set ? "alive" : "partial"}>
          {data?.source === "env" ? "环境变量" : "运行时配置"} · {data?.api_key_set ? "Key 已配置" : "未配置 Key"}
        </span>
      </div>
      <p className="muted small">
        保存后由 worker 在下一个任务读取。API Key 只会回显末四位，完整值不再返回；设置仅管理员可改。
      </p>
      <div className="grid-2" style={{ marginTop: 14 }}>
        <label className="field">
          提供方
          <select value={provider} onChange={(event) => setProvider(event.target.value)} disabled={query.isPending || saving}>
            {PROVIDERS.map((item) => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>
        </label>
        <label className="field">
          推理强度
          <select value={reasoning} onChange={(event) => setReasoning(event.target.value)} disabled={!needsConnection || saving}>
            <option value="">默认</option>
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
          </select>
        </label>
        <label className="field">
          Base URL{customNeedsBase ? "（custom 必填）" : "（可选）"}
          <input
            type="url"
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.target.value)}
            placeholder="https://gateway.example.com/v1"
            disabled={!needsConnection || saving}
          />
        </label>
        <label className="field">
          模型名
          <input
            type="text"
            value={model}
            onChange={(event) => setModel(event.target.value)}
            placeholder="deepseek-chat / gpt-4o-mini / claude-..."
            disabled={!needsConnection || saving}
          />
        </label>
        <label className="field">
          API Key
          <input
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={data?.api_key_set ? `已保存（${data.api_key_hint ?? "****"}），留空保持不变` : "sk-..."}
            disabled={!needsConnection || clearKey || saving}
            autoComplete="new-password"
          />
        </label>
        <label className="check" style={{ alignSelf: "end", paddingBottom: 9 }}>
          <input type="checkbox" checked={clearKey} onChange={(event) => setClearKey(event.target.checked)} disabled={!needsConnection || saving} />
          清除已保存的 API Key
        </label>
      </div>
      <div className="row" style={{ marginTop: 14 }}>
        <button className="btn btn-primary" type="button" onClick={() => void save()} disabled={saving || query.isPending}>
          {saving ? "保存中…" : "保存模型配置"}
        </button>
        <button className="btn" type="button" onClick={() => void runTest()} disabled={testing || saving || query.isPending}>
          {testing ? "测试中…" : "测试连接"}
        </button>
      </div>
      {error ? <p className="small fatal" role="alert">{error}</p> : null}
      {message ? <p className="small ok">{message}</p> : null}
      {test ? (
        <div className={`banner ${test.ok ? "" : "banner-dead"}`} style={{ marginTop: 12 }}>
          <strong>{test.ok ? "连接成功" : "连接失败"}</strong>
          <span className="muted small" style={{ marginLeft: 8 }}>
            {test.provider}{test.model ? ` / ${test.model}` : ""}{test.latency_ms !== null ? ` · ${test.latency_ms}ms` : ""}
          </span>
          {test.detail ? <p className="small mono" style={{ marginBottom: 0 }}>{test.detail}</p> : null}
        </div>
      ) : null}
    </section>
  );
}
