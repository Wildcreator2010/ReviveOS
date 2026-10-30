import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { AddressInfo } from "node:net";
import { extname, join, normalize, resolve, sep } from "node:path";

const MIME: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8",
  ".webmanifest": "application/manifest+json",
};

export interface StaticHost {
  url: string;
  port: number;
  close(): Promise<void>;
}

/**
 * Minimal loopback file server for the static Next.js export bundled in the asar.
 *
 * Why not load the export over file:// ? Next's exported HTML references /_next/...
 * with absolute paths and the browser blocks cross-origin file reads; serving from
 * 127.0.0.1 keeps routing, RSC payloads and assets working exactly as they do on the
 * web, with no Node integration in the renderer.
 */
export async function startStaticHost(root: string): Promise<StaticHost> {
  const base = resolve(root);
  if (!existsSync(join(base, "index.html"))) {
    throw new Error(`静态导出目录无效（缺少 index.html）：${base}`);
  }
  const server: Server = createServer((request, response) => handle(base, request, response));
  await new Promise<void>((resolveListen, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolveListen());
  });
  const address = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${address.port}`,
    port: address.port,
    close: () =>
      new Promise<void>((resolveClose) => {
        server.close(() => resolveClose());
      }),
  };
}

const SECURITY_HEADERS = {
  "Content-Security-Policy":
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: http: https:; font-src 'self' data:; connect-src 'self' http: https:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "Cross-Origin-Resource-Policy": "same-origin",
} as const;

function handle(base: string, request: IncomingMessage, response: ServerResponse): void {
  const hostHeader = (request.headers.host ?? "").toLowerCase();
  const host = hostHeader.startsWith("[")
    ? hostHeader.slice(0, hostHeader.indexOf("]") + 1)
    : (hostHeader.split(":")[0] ?? "");
  if (host && host !== "127.0.0.1" && host !== "localhost" && host !== "[::1]") {
    response.writeHead(403, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("403");
    return;
  }
  const rawPath = (request.url ?? "/").split("?")[0] ?? "/";
  let decoded: string;
  try {
    decoded = decodeURIComponent(rawPath);
  } catch {
    response.writeHead(400, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("400");
    return;
  }
  if (decoded.split(/[\\/]+/).some((segment) => segment === "..")) {
    response.writeHead(400, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("400");
    return;
  }
  const safe = normalize(decoded).replace(/^([.][.][/\\])+/, "");
  const candidates = candidatePaths(base, safe);
  for (const candidate of candidates) {
    if (!candidate.startsWith(base + sep) && candidate !== base) continue;
    if (!existsSync(candidate)) continue;
    const stats = statSync(candidate);
    if (!stats.isFile()) continue;
    const type = MIME[extname(candidate).toLowerCase()] ?? "application/octet-stream";
    response.writeHead(200, {
      "Content-Type": type,
      "Content-Length": stats.size,
      "Cache-Control": "no-store",
      ...SECURITY_HEADERS,
    });
    createReadStream(candidate).pipe(response);
    return;
  }
  response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8", ...SECURITY_HEADERS });
  response.end("404");
}

function candidatePaths(base: string, safePath: string): string[] {
  const joined = join(base, safePath);
  const candidates: string[] = [];
  // Windows normalize() returns backslashes; URL routing must still see segments.
  const urlPath = safePath.replace(/\\/g, "/");
  const segments = urlPath.split("/").filter((segment) => segment.length > 0);
  // Dynamic routes are exported once under <route>/__runtime__/; map a concrete
  // id (and optional sub-route) onto that shell before trying SPA fallbacks.
  const [first, second] = segments;
  if (first && second && ["jobs", "projects", "capsules"].includes(first) && second !== "__runtime__") {
    const runtime = join(base, first, "__runtime__", ...segments.slice(2));
    candidates.push(runtime);
    candidates.push(`${runtime}.html`);
    candidates.push(join(runtime, "index.html"));
  }
  if (urlPath.endsWith("/")) {
    candidates.push(join(joined, "index.html"));
  } else {
    candidates.push(joined);
    candidates.push(`${joined}.html`);
    candidates.push(join(joined, "index.html"));
  }
  // Any remaining client-side route gets the app shell; assets keep their real
  // extension and fall through to the 404 page instead.
  if (!extname(urlPath)) {
    candidates.push(join(base, "index.html"));
  }
  candidates.push(join(base, "404.html"));
  return candidates;
}
