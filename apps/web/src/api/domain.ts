/**
 * Runtime readers for control-plane payloads.
 *
 * BLOCKED on schemas/openapi/openapi.json (T-FE-02): the generated components do not
 * exist yet, so nothing here may invent fields. Each reader accepts `unknown` and pulls
 * only values that are actually present; missing values stay `null` and the UI renders an
 * explicit empty/unknown state instead of a fabricated number.
 */

export type Json = Record<string, unknown>;

export const isRecord = (value: unknown): value is Json =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export function asRecord(value: unknown): Json | null {
  return isRecord(value) ? value : null;
}

export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function str(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

export function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function bool(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

/** ISO-8601 string straight from the API; the UI never invents a timestamp. */
export function timestamp(value: unknown): string | null {
  const raw = str(value);
  if (!raw) return null;
  const parsed = Date.parse(raw);
  return Number.isFinite(parsed) ? raw : null;
}

/** Reads a dotted path out of a nested JSON object. */
export function pick(value: unknown, path: string): unknown {
  let cursor: unknown = value;
  for (const segment of path.split(".")) {
    if (!isRecord(cursor)) return undefined;
    cursor = cursor[segment];
  }
  return cursor;
}

export function pickStr(value: unknown, path: string): string | null {
  return str(pick(value, path));
}

export function pickNum(value: unknown, path: string): number | null {
  return num(pick(value, path));
}

export function pickArray(value: unknown, path: string): unknown[] {
  return asArray(pick(value, path));
}

/** Extracts `items` from either a bare array or the paginated `{ items, next_cursor }` envelope. */
export function itemsOf(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  const record = asRecord(value);
  if (!record) return [];
  if (Array.isArray(record.items)) return record.items;
  if (Array.isArray(record.data)) return record.data;
  if (Array.isArray(record.results)) return record.results;
  return [];
}

export function nextCursorOf(value: unknown): string | null {
  return pickStr(value, "next_cursor") ?? pickStr(value, "next") ?? pickStr(value, "cursor");
}
