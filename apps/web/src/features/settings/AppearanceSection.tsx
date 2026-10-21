"use client";

import { useRef, useState } from "react";
import { DEFAULT_WALLPAPER, MAX_WALLPAPER_DATA_URL, saveWallpaper, useWallpaper } from "../../../components/theme/wallpaper";

const PRESETS = [
  { label: "默认山谷", value: DEFAULT_WALLPAPER },
  { label: "海岸", value: "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=2400&q=80" },
  { label: "夜山", value: "https://images.unsplash.com/photo-1519681393784-d120267933ba?auto=format&fit=crop&w=2400&q=80" },
  { label: "城市", value: "https://images.unsplash.com/photo-1477959858617-67f85cf4f1df?auto=format&fit=crop&w=2400&q=80" },
] as const;

export function AppearanceSection() {
  const wallpaper = useWallpaper();
  const [draft, setDraft] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  function apply(value: string | null) {
    const result = saveWallpaper(value);
    if (!result.ok) {
      setError(result.reason ?? "保存失败");
      return;
    }
    setError(null);
    setMessage(value ? "壁纸已更新。" : "已恢复默认壁纸。");
    setDraft("");
    setTimeout(() => setMessage(null), 2500);
  }

  function upload(file: File | undefined) {
    if (!file) return;
    if (file.size > 1_500_000) {
      setError("图片超过 1.5 MB，请压缩后重试，或直接填写图片 URL。");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const value = typeof reader.result === "string" ? reader.result : "";
      if (value.length > MAX_WALLPAPER_DATA_URL) {
        setError("图片编码后过大，请换一张更小的图片。");
        return;
      }
      apply(value);
    };
    reader.onerror = () => setError("读取图片失败。");
    reader.readAsDataURL(file);
  }

  return (
    <section className="panel">
      <p className="eyebrow">APPEARANCE</p>
      <h2>壁纸与外观</h2>
      <p className="muted small">壁纸只保存在当前浏览器；支持图片 URL 或本地上传，全站即时生效。</p>
      <div className="wallpaper-preview" style={{ backgroundImage: `url("${draft.trim() || wallpaper || DEFAULT_WALLPAPER}")`, marginTop: 14 }}>
        <span>{draft.trim() ? "预览（尚未应用）" : "当前壁纸"}</span>
      </div>
      <div className="row" style={{ marginTop: 10 }}>
        <span className="muted small">预设：</span>
        {PRESETS.map((preset) => (
          <button key={preset.label} className="btn small" type="button" onClick={() => apply(preset.value)}>
            {preset.label}
          </button>
        ))}
      </div>
      <div className="grid-2" style={{ marginTop: 14 }}>
        <label className="field">
          图片 URL
          <input
            type="url"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="https://images.example.com/wallpaper.jpg"
          />
        </label>
        <div className="row" style={{ alignSelf: "end", gap: 8 }}>
          <button className="btn btn-primary" type="button" disabled={!draft.trim()} onClick={() => apply(draft.trim())}>
            应用 URL
          </button>
          <button className="btn" type="button" onClick={() => fileRef.current?.click()}>
            上传本地图片
          </button>
          <button className="btn btn-ghost" type="button" onClick={() => apply(null)}>
            恢复默认
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            hidden
            onChange={(event) => {
              upload(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
        </div>
      </div>
      {error ? <p className="small fatal" role="alert">{error}</p> : null}
      {message ? <p className="small ok">{message}</p> : null}
    </section>
  );
}
