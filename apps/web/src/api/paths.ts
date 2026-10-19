import type { ApiPath } from "./types.gen";

/**
 * Canonical control-plane paths.
 *
 * BLOCKED (T-FE-02): these literals come from the backend task contract because the
 * OpenAPI snapshot has not been published yet. Once `schemas/openapi/openapi.json`
 * exists, `make gen-web` regenerates types.gen.ts and this file becomes redundant —
 * every entry is checked against the generated `paths` union TODAY, so a rename in
 * the snapshot fails the type-check instead of silently drifting.
 */
export const API_PATHS = {
  health: "/healthz",
  ready: "/readyz",
  register: "/api/v1/auth/register",
  login: "/api/v1/auth/login",
  refresh: "/api/v1/auth/refresh",
  apiKeys: "/api/v1/auth/api-keys",
  apiKey: (id: string) => `/api/v1/auth/api-keys/${encodeURIComponent(id)}` as ApiPath,
  me: "/api/v1/me",
  projects: "/api/v1/projects",
  project: (id: string) => `/api/v1/projects/${encodeURIComponent(id)}` as ApiPath,
  projectResurrect: (id: string) => `/api/v1/projects/${encodeURIComponent(id)}/resurrect` as ApiPath,
  projectGenome: (id: string) => `/api/v1/projects/${encodeURIComponent(id)}/genome` as ApiPath,
  projectBuilds: (id: string) => `/api/v1/projects/${encodeURIComponent(id)}/builds` as ApiPath,
  projectPatches: (id: string) => `/api/v1/projects/${encodeURIComponent(id)}/patches` as ApiPath,
  projectBehavior: (id: string) => `/api/v1/projects/${encodeURIComponent(id)}/behavior` as ApiPath,
  projectScore: (id: string) => `/api/v1/projects/${encodeURIComponent(id)}/score` as ApiPath,
  projectEvidence: (id: string) => `/api/v1/projects/${encodeURIComponent(id)}/evidence` as ApiPath,
  projectCapsules: (id: string) => `/api/v1/projects/${encodeURIComponent(id)}/capsules` as ApiPath,
  jobs: "/api/v1/jobs",
  job: (id: string) => `/api/v1/jobs/${encodeURIComponent(id)}` as ApiPath,
  /**
   * SSE endpoint. The task brief says /api/v1/jobs/{id}/events; backend task T-BE-06
   * freezes /api/v1/jobs/{id}/events/stream (Last-Event-ID replay + 15s heartbeat).
   * The backend contract wins; flip this one constant if that changes.
   */
  jobEventsStream: (id: string) => `/api/v1/jobs/${encodeURIComponent(id)}/events/stream` as ApiPath,
  jobEvents: (id: string) => `/api/v1/jobs/${encodeURIComponent(id)}/events` as ApiPath,
  jobCancel: (id: string) => `/api/v1/jobs/${encodeURIComponent(id)}/cancel` as ApiPath,
  capsule: (id: string) => `/api/v1/capsules/${encodeURIComponent(id)}` as ApiPath,
  capsuleDownload: (id: string) => `/api/v1/capsules/${encodeURIComponent(id)}/download` as ApiPath,
} as const;
