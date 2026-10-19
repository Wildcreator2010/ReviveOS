"use client";

import { useQuery, type QueryKey } from "@tanstack/react-query";
import { ApiError, apiBaseUrl, apiGet } from "../api/client";

export interface ApiQueryError {
  code: string;
  message: string;
  /** True when the control plane could not be reached at all (offline/desktop cold start). */
  offline: boolean;
  retryAfterSeconds: number | null;
}

export function describeApiError(error: unknown): ApiQueryError {
  if (error instanceof ApiError) {
    const offline = error.status === 0 || error.code === "network_unreachable";
    return {
      code: error.code,
      message: offline ? apiBaseUrl() : error.message,
      offline,
      retryAfterSeconds: error.retryAfterSeconds,
    };
  }
  return { code: "unknown", message: error instanceof Error ? error.message : String(error), offline: false, retryAfterSeconds: null };
}

/** Read-only API resource with the standard loading/error/offline projection. */
export function useApiQuery<T = unknown>(queryKey: QueryKey, path: string, query?: Record<string, string | number | undefined>, enabled = true) {
  const result = useQuery({
    queryKey,
    queryFn: () => apiGet<T>(path, { query }),
    enabled,
  });
  return {
    data: result.data,
    isLoading: result.isPending && enabled,
    error: result.error ? describeApiError(result.error) : null,
    refresh: () => void result.refetch(),
    isFetching: result.isFetching,
  };
}
