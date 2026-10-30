import { cpSync, existsSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../../..");
const source = join(repoRoot, "apps", "web", "out");
const destination = join(here, "..", "web");

if (!existsSync(join(source, "index.html"))) {
  console.error(`web export missing: ${source} (run pnpm --filter web build first)`);
  process.exit(1);
}

rmSync(destination, { recursive: true, force: true });
cpSync(source, destination, { recursive: true });
console.log(`copied ${source} -> ${destination}`);
