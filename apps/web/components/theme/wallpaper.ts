"use client";

import { useEffect, useState } from "react";

export const DEFAULT_WALLPAPER = "/wallpaper.jpg";
const STORAGE_KEY = "revive.wallpaper";
const CHANGE_EVENT = "revive-wallpaper";
export const MAX_WALLPAPER_DATA_URL = 2_000_000;

function normalize(value: string | null | undefined): string | null {
  const text = (value ?? "").trim();
  if (!text) return null;
  if (/["'\r\n]/.test(text)) return null;
  if (text.startsWith("data:image/")) return text;
  if (text.startsWith("/")) return text;
  if (/^https?:\/\//i.test(text)) return text;
  return null;
}

export function loadWallpaper(): string {
  if (typeof window === "undefined") return DEFAULT_WALLPAPER;
  try {
    return normalize(window.localStorage.getItem(STORAGE_KEY)) ?? DEFAULT_WALLPAPER;
  } catch {
    return DEFAULT_WALLPAPER;
  }
}

export function saveWallpaper(value: string | null): { ok: boolean; reason?: string } {
  if (typeof window === "undefined") return { ok: false, reason: "no-window" };
  const normalized = normalize(value);
  if (value && !normalized) return { ok: false, reason: "仅支持 http(s)、站内路径或图片 Data URL。" };
  if (normalized && normalized.length > MAX_WALLPAPER_DATA_URL) {
    return { ok: false, reason: "图片过大，请使用 1.5 MB 以内的文件或改用图片 URL。" };
  }
  try {
    if (normalized) window.localStorage.setItem(STORAGE_KEY, normalized);
    else window.localStorage.removeItem(STORAGE_KEY);
    window.dispatchEvent(new Event(CHANGE_EVENT));
    return { ok: true };
  } catch {
    return { ok: false, reason: "浏览器存储空间不足，请改用图片 URL。" };
  }
}

export function useWallpaper(): string {
  const [wallpaper, setWallpaper] = useState(DEFAULT_WALLPAPER);
  useEffect(() => {
    const update = () => setWallpaper(loadWallpaper());
    update();
    window.addEventListener(CHANGE_EVENT, update);
    window.addEventListener("storage", update);
    return () => {
      window.removeEventListener(CHANGE_EVENT, update);
      window.removeEventListener("storage", update);
    };
  }, []);
  return wallpaper;
}
