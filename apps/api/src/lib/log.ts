/** Structured JSON logging: one line per event, never passwords/tokens/full PII. */

type Level = "info" | "warn" | "error";

// Keys whose values must never reach the logs
const REDACT = /pass|token|secret|authorization|api[-_]?key|cookie|otp|phone|email/i;

function clean(fields: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(fields)) {
    out[k] = REDACT.test(k) ? "[redacted]" : v;
  }
  return out;
}

function emit(level: Level, event: string, fields: Record<string, unknown> = {}) {
  const line = JSON.stringify({ ts: new Date().toISOString(), level, event, ...clean(fields) });
  (level === "error" ? console.error : console.log)(line);
}

export const log = {
  info: (event: string, fields?: Record<string, unknown>) => emit("info", event, fields),
  warn: (event: string, fields?: Record<string, unknown>) => emit("warn", event, fields),
  error: (event: string, fields?: Record<string, unknown>) => emit("error", event, fields),
};
