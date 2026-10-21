import { asRecord, itemsOf, nextCursorOf, num, pick, pickNum, pickStr, str, timestamp, type Json } from "./domain";
import type { CapsuleStatus, EventType, JobEvent, JobStatus } from "./domain-types";
import { isEventType } from "./events";

export { nextCursorOf } from "./domain";

export interface ProjectSummary {
  id: string;
  repoUrl: string | null;
  repo: string | null;
  commit: string | null;
  status: string | null;
  latestScore: number | null;
  updatedAt: string | null;
  createdAt: string | null;
  raw: Json;
}

export interface JobSummary {
  id: string;
  projectId: string | null;
  status: JobStatus;
  rawStatus: string | null;
  createdAt: string | null;
  finishedAt: string | null;
  errorCode: string | null;
  raw: Json;
}

export interface GenomeField {
  key: string;
  label: string;
  version: string | null;
  image: string | null;
  confidence: number | null;
  evidence: EvidenceItem[];
  /** True when the value came from an LLM strengthening pass (must be badged as AI 补强). */
  fromLlm: boolean;
  raw: unknown;
}

export interface EvidenceItem {
  sourceKind: string;
  reference: string;
  note: string | null;
  confidence: number | null;
}

export interface GenomeView {
  fields: GenomeField[];
  overallConfidence: number | null;
  dependencies: EvidenceItem[];
  lowConfidenceCount: number;
  raw: Json;
}

export interface ScoreComponent {
  key: string;
  label: string;
  value: number | null;
  weight: number | null;
}

export interface ScoreView {
  total: number | null;
  components: ScoreComponent[];
  raw: Json;
}

export interface PatchView {
  id: string;
  index: number | null;
  summary: string | null;
  rationale: string | null;
  risk: string | null;
  result: string | null;
  rolledBack: boolean;
  refused: boolean;
  refusedReason: string | null;
  signature: string | null;
  diff: string | null;
  files: string[];
  raw: Json;
}

export interface BehaviorCase {
  name: string;
  status: string | null;
  expected: string | null;
  actual: string | null;
  epsilon: number | null;
  drift: string | null;
}

export interface BehaviorView {
  available: boolean;
  compatibility: number | null;
  reason: string | null;
  cases: BehaviorCase[];
  raw: Json;
}

export interface CapsuleView {
  id: string;
  status: CapsuleStatus;
  format: string | null;
  repo: string | null;
  commit: string | null;
  scoreTotal: number | null;
  patchCount: number | null;
  sbomDigest: string | null;
  createdAt: string | null;
  downloadUrl: string | null;
  raw: Json;
}

export function readProject(value: unknown): ProjectSummary | null {
  const raw = asRecord(value);
  if (!raw) return null;
  const id = str(raw.id) ?? str(raw.project_id);
  if (!id) return null;
  return {
    id,
    repoUrl: str(raw.repo_url) ?? pickStr(raw, "source.repo"),
    repo: str(raw.repo) ?? pickStr(raw, "repository.full_name"),
    commit: str(raw.commit) ?? pickStr(raw, "repository.default_branch_commit"),
    status: str(raw.status),
    latestScore: num(raw.latest_score) ?? pickNum(raw, "score.total"),
    updatedAt: timestamp(raw.updated_at),
    createdAt: timestamp(raw.created_at),
    raw,
  };
}

export function readProjects(value: unknown): ProjectSummary[] {
  return itemsOf(value)
    .map(readProject)
    .filter((project): project is ProjectSummary => project !== null);
}

const JOB_STATUSES: readonly JobStatus[] = ["queued", "running", "succeeded", "failed", "cancelled", "cancel_requested"];

export function readJob(value: unknown): JobSummary | null {
  const raw = asRecord(value);
  if (!raw) return null;
  const id = str(raw.id) ?? str(raw.job_id);
  if (!id) return null;
  const rawStatus = str(raw.status);
  const status = rawStatus && (JOB_STATUSES as readonly string[]).includes(rawStatus) ? (rawStatus as JobStatus) : "unknown";
  return {
    id,
    projectId: str(raw.project_id),
    status,
    rawStatus,
    createdAt: timestamp(raw.created_at),
    finishedAt: timestamp(raw.finished_at) ?? timestamp(raw.updated_at),
    errorCode: pickStr(raw, "error.code") ?? str(raw.error_code),
    raw,
  };
}

export function readJobs(value: unknown): JobSummary[] {
  return itemsOf(value)
    .map(readJob)
    .filter((job): job is JobSummary => job !== null);
}

export function readEvent(value: unknown): JobEvent | null {
  const raw = asRecord(value);
  if (!raw) return null;
  const id = str(raw.id);
  const jobId = str(raw.job_id);
  const projectId = str(raw.project_id);
  const ts = timestamp(raw.ts);
  const type = raw.type;
  if (!id || !jobId || !isEventType(type)) return null;
  return {
    id,
    job_id: jobId,
    project_id: projectId ?? "",
    ts: ts ?? "",
    type: type as EventType,
    payload: asRecord(raw.payload) ?? {},
  };
}

function readEvidenceList(value: unknown): EvidenceItem[] {
  return itemsOf(value)
    .map((entry) => {
      const raw = asRecord(entry);
      if (!raw) return null;
      const reference = str(raw.reference);
      if (!reference) return null;
      return {
        sourceKind: str(raw.source_kind) ?? "inference",
        reference,
        note: str(raw.note),
        confidence: num(raw.confidence),
      };
    })
    .filter((item): item is EvidenceItem => item !== null);
}

function readGenomeInference(value: unknown): { version: string | null; image: string | null; confidence: number | null; evidence: EvidenceItem[] } {
  const raw = asRecord(value) ?? {};
  return {
    version: str(raw.version),
    image: str(raw.image),
    confidence: num(raw.confidence),
    evidence: readEvidenceList(raw.evidence),
  };
}

const GENOME_FIELDS: readonly { key: string; label: string }[] = [
  { key: "python", label: "Python" },
  { key: "os", label: "操作系统" },
];

export function readGenome(value: unknown): GenomeView | null {
  const container = asRecord(value);
  const payload = container && "genome" in container ? container.genome : value;
  const raw = asRecord(payload);
  if (!raw) return null;
  const fields: GenomeField[] = [];
  for (const { key, label } of GENOME_FIELDS) {
    const inference = readGenomeInference(raw[key]);
    const fromLlm = str(pick(raw[key], "llm_reason")) !== null;
    fields.push({ key, label, version: inference.version, image: inference.image, confidence: inference.confidence, evidence: inference.evidence, fromLlm, raw: raw[key] });
  }
  const cuda = readGenomeInference(raw.cuda);
  fields.push({ key: "cuda", label: "CUDA", version: cuda.version, image: cuda.image, confidence: cuda.confidence, evidence: cuda.evidence, fromLlm: str(pick(raw.cuda, "llm_reason")) !== null, raw: raw.cuda });
  for (const [index, entry] of (Array.isArray(raw.system_libs) ? raw.system_libs : []).entries()) {
    const inference = readGenomeInference(entry);
    fields.push({ key: `system_libs[${index}]`, label: `系统库 #${index + 1}`, version: inference.version, image: inference.image, confidence: inference.confidence, evidence: inference.evidence, fromLlm: str(pick(entry, "llm_reason")) !== null, raw: entry });
  }
  const dependencies: EvidenceItem[] = itemsOf(raw.dependencies)
    .map((entry) => {
      const dep = asRecord(entry);
      if (!dep) return null;
      const name = str(dep.name);
      if (!name) return null;
      return {
        sourceKind: str(dep.source) ?? "inference",
        reference: `${name}@${str(dep.version) ?? "?"}`,
        note: str(dep.note),
        confidence: num(dep.confidence),
      };
    })
    .filter((item): item is EvidenceItem => item !== null);
  const confidenceValues = fields.map((field) => field.confidence).filter((value): value is number => value !== null);
  return {
    fields,
    overallConfidence: num(raw.overall_confidence),
    dependencies,
    lowConfidenceCount: confidenceValues.filter((value) => value < 0.7).length,
    raw,
  };
}

const SCORE_COMPONENTS: readonly { key: string; label: string }[] = [
  { key: "runtime", label: "运行时" },
  { key: "dependencies", label: "依赖" },
  { key: "build", label: "构建" },
  { key: "tests", label: "测试" },
  { key: "behavior", label: "行为" },
  { key: "reproducibility", label: "可复现性" },
];

/** Weights mirror schemas/resurrection-score.schema.json x-weights — display only, never recomputed. */
export const SCORE_WEIGHTS: Record<string, number> = {
  runtime: 0.2,
  dependencies: 0.2,
  build: 0.15,
  tests: 0.15,
  behavior: 0.2,
  reproducibility: 0.1,
};

export function readScore(value: unknown): ScoreView | null {
  const container = asRecord(value);
  const payload = container && "score" in container ? container.score : value;
  const raw = asRecord(payload);
  if (!raw) return null;
  const components = SCORE_COMPONENTS.map(({ key, label }) => ({
    key,
    label,
    value: num(raw[key]),
    weight: SCORE_WEIGHTS[key] ?? null,
  }));
  return { total: num(raw.total), components, raw };
}

export function readPatches(value: unknown): PatchView[] {
  return itemsOf(value)
    .map((entry, index): PatchView | null => {
      const raw = asRecord(entry);
      if (!raw) return null;
      const result = pickStr(raw, "result.status") ?? str(raw.result);
      return {
        id: str(raw.id) ?? `patch-${index}`,
        index: num(raw.index) ?? num(raw.seq) ?? index + 1,
        summary: str(raw.summary) ?? str(raw.title),
        rationale: str(raw.rationale) ?? pickStr(raw, "rationale.summary"),
        risk: str(raw.risk) ?? pickStr(raw, "risk.level"),
        result,
        rolledBack: raw.rolled_back === true || result === "rolled_back",
        refused: raw.refused === true || result === "refused",
        refusedReason: pickStr(raw, "refused.reason") ?? str(raw.refused_reason),
        signature: pickStr(raw, "error_fact.signature"),
        diff: str(raw.diff) ?? str(raw.unified_diff),
        files: itemsOf(raw.files).map((file) => str(file) ?? "").filter((file) => file.length > 0),
        raw,
      };
    })
    .filter((patch): patch is PatchView => patch !== null);
}

export function readBehavior(value: unknown): BehaviorView | null {
  const container = asRecord(value);
  const payload = container && "behavior" in container ? container.behavior : value;
  const raw = asRecord(payload);
  if (!raw) return null;
  const compatibility = num(raw.compatibility) ?? num(pick(raw, "summary.compatibility"));
  const cases = itemsOf(raw.cases)
    .map((entry) => {
      const item = asRecord(entry);
      if (!item) return null;
      const name = str(item.name) ?? str(item.case_id);
      if (!name) return null;
      return {
        name,
        status: str(item.status),
        expected: str(item.expected) ?? jsonish(item.expected_value),
        actual: str(item.actual) ?? jsonish(item.actual_value),
        epsilon: num(item.epsilon) ?? num(pick(item, "tolerance.epsilon")),
        drift: str(item.drift) ?? pickStr(item, "drift.summary"),
      };
    })
    .filter((item): item is BehaviorCase => item !== null);
  return {
    available: compatibility !== null,
    compatibility,
    reason: str(raw.reason) ?? pickStr(raw, "baseline.reason"),
    cases,
    raw,
  };
}

function jsonish(value: unknown): string | null {
  if (value === undefined || value === null) return null;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return null;
  }
}

export function readCapsule(value: unknown): CapsuleView | null {
  const raw = asRecord(value);
  if (!raw) return null;
  const id = str(raw.id) ?? str(raw.capsule_id);
  if (!id) return null;
  const manifest = asRecord(raw.manifest) ?? {};
  const status = str(manifest.status) ?? str(raw.status);
  return {
    id,
    status: status === "alive" || status === "partial" || status === "dead" ? status : "unknown",
    format: str(manifest.format) ?? str(raw.format),
    repo: pickStr(manifest, "source.repo") ?? pickStr(raw, "source.repo"),
    commit: pickStr(manifest, "source.commit") ?? pickStr(raw, "source.commit"),
    scoreTotal: pickNum(manifest, "score.total") ?? pickNum(raw, "score.total"),
    patchCount: Array.isArray(pick(manifest, "patches")) ? (pick(manifest, "patches") as unknown[]).length : null,
    sbomDigest: str(manifest.sbom_digest) ?? str(raw.sbom_digest),
    createdAt: timestamp(raw.created_at),
    downloadUrl: str(raw.download_url),
    raw,
  };
}

export function readCapsules(value: unknown): CapsuleView[] {
  return itemsOf(value)
    .map(readCapsule)
    .filter((capsule): capsule is CapsuleView => capsule !== null);
}

export function readApiKeys(value: unknown): { id: string; prefix: string; label: string | null; createdAt: string | null }[] {
  return itemsOf(value)
    .map((entry) => {
      const raw = asRecord(entry);
      if (!raw) return null;
      const id = str(raw.id);
      const prefix = str(raw.prefix) ?? str(raw.key_prefix);
      if (!id || !prefix) return null;
      return { id, prefix, label: str(raw.label) ?? str(raw.name), createdAt: timestamp(raw.created_at) };
    })
    .filter((key): key is { id: string; prefix: string; label: string | null; createdAt: string | null } => key !== null);
}
