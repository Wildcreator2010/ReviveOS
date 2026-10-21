"use client";

import { usePathname } from "next/navigation";

/**
 * Next static export prunes dynamic params into a single `__runtime__` page, so
 * useParams() returns "__runtime__" even when a direct link carries a real id.
 * The pathname is the only reliable source for client-side dynamic routes.
 */
export function useRouteId(kind: "jobs" | "projects" | "capsules"): string {
  const pathname = usePathname() ?? "";
  const segments = pathname.split("/").filter((segment) => segment.length > 0);
  if (segments[0] !== kind) return "";
  const value = segments[1] ?? "";
  if (!value || value === "__runtime__") return "";
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}
