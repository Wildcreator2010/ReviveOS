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

function handle(base: string, request: IncomingMessage, response: ServerResponse): void {
  const rawPath = (request.url ?? "/").split("?")[0] ?? "/";
  const decoded = decodeURIComponent(rawPath);
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
      "X-Content-Type-Options": "nosniff",
    });
    createReadStream(candidate).pipe(response);
    return;
  }
  response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
  response.end("404");
}

function candidatePaths(base: string, safePath: string): string[] {
  const joined = join(base, safePath);
  const candidates: string[] = [];
  if (safePath.endsWith("/")) {
    candidates.push(join(joined, "index.html"));
  } else {
    candidates.push(joined);
    candidates.push(`${joined}.html`);
    candidates.push(join(joined, "index.html"));
  }
  // Client-side dynamic routes (/jobs/<id>) are not prerendered: fall back to the
  // exported 404 page, which is a real Next.js page and renders the app shell.
  candidates.push(join(base, "404.html"));
  return candidates;
}
