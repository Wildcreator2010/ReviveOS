#!/usr/bin/env node
/**
 * Generates apps/web/src/api/types.gen.ts from schemas/openapi/openapi.json.
 *
 * BLOCKED until the backend publishes the snapshot (T-BE-03): when the file is
 * missing this script exits non-zero and says so, instead of emitting a guessed
 * client. That is intentional — hand-written interface types are forbidden.
 *
 * Usage: node scripts/gen-api.mjs   (or: make gen-web)
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../../..");
const snapshot = resolve(repoRoot, "schemas/openapi/openapi.json");
const target = resolve(here, "../src/api/types.gen.ts");

if (!existsSync(snapshot)) {
  console.error(`[gen-api] BLOCKED: ${snapshot} does not exist yet.`);
  console.error("[gen-api] The backend (T-BE-03) must publish the OpenAPI snapshot first (make openapi).");
  console.error("[gen-api] apps/web/src/api/types.gen.ts keeps its placeholder path map until then.");
  process.exit(2);
}

let openapiTypescript;
try {
  openapiTypescript = await import("openapi-typescript");
} catch {
  console.error("[gen-api] BLOCKED: openapi-typescript is not installed.");
  console.error("[gen-api] Run: pnpm --filter web add -D openapi-typescript@^7");
  process.exit(3);
}

const schema = JSON.parse(readFileSync(snapshot, "utf8"));
const ast = await openapiTypescript.default(schema, {});
const source = openapiTypescript.astToString(ast);
const header = `// GENERATED FROM schemas/openapi/openapi.json - DO NOT EDIT\n// openapi: ${schema.openapi ?? "unknown"}; title: ${schema.info?.title ?? "unknown"}; version: ${schema.info?.version ?? "unknown"}\n\n`;
const apiPathAlias = source.replace("export interface paths {", "export type ApiPath = keyof paths;\n\nexport interface paths {");
mkdirSync(dirname(target), { recursive: true });
writeFileSync(target, header + apiPathAlias, "utf8");
console.log(`[gen-api] wrote ${target}`);
