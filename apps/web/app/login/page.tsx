"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { ApiError, apiBaseUrl, setApiBaseUrl } from "../../src/api/client";
import { login, register } from "../../src/api/auth";
import { desktopBridge } from "../../src/desktop/bridge";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [apiBase, setApiBase] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function applyApiBase(): Promise<void> {
    const next = apiBase.trim();
    if (!next) return;
    setApiBaseUrl(next);
    try {
      window.localStorage.setItem("revive.apiBaseUrl", next);
    } catch {
      /* storage unavailable: the in-memory override still applies */
    }
    const bridge = desktopBridge();
    if (bridge) await bridge.setApiBaseUrl(next);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    if (email.trim().length === 0 || password.length < 8) {
      setError("请输入邮箱和至少 8 位密码。");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await applyApiBase();
      if (mode === "login") await login(email.trim(), password);
      else await register(email.trim(), password);
      router.replace("/");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="stack" style={{ maxWidth: 520, margin: "40px auto" }}>
      <section className="panel">
        <p className="eyebrow">ACCESS</p>
        <h1>{mode === "login" ? "登录控制台" : "注册账号"}</h1>
        <p className="muted small">
          控制台只使用你自己的账号数据。密码经 Argon2 哈希保存；登录后访问令牌只保存在当前浏览器会话中。
        </p>
        <form className="stack" onSubmit={submit}>
          <label className="field">
            控制面地址（可选，桌面版或远程 API）
            <input
              type="url"
              value={apiBase}
              onChange={(event) => setApiBase(event.target.value)}
              placeholder={apiBaseUrl() || "留空使用当前站点同源地址"}
            />
          </label>
          <label className="field">
            邮箱
            <input
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
              required
            />
          </label>
          <label className="field">
            密码
            <input
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="至少 8 位"
              minLength={8}
              required
            />
          </label>
          {error ? (
            <p className="muted small" role="alert" style={{ color: "var(--danger, #c0392b)" }}>
              {error}
            </p>
          ) : null}
          <div className="row" style={{ gap: 12, alignItems: "center" }}>
            <button className="btn btn-primary" type="submit" disabled={submitting}>
              {submitting ? "正在提交…" : mode === "login" ? "登录" : "注册并登录"}
            </button>
            <button
              className="btn small"
              type="button"
              onClick={() => {
                setMode(mode === "login" ? "register" : "login");
                setError(null);
              }}
            >
              {mode === "login" ? "没有账号？注册" : "已有账号？登录"}
            </button>
          </div>
        </form>
        <p className="muted small" style={{ marginTop: 16 }}>
          <Link href="/">返回控制台</Link>
        </p>
      </section>
    </div>
  );
}
