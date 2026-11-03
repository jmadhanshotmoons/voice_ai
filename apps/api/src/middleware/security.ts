/**
 * Security middleware stack.
 *
 *  1. Helmet            security headers (strict CSP, HSTS 2y, COOP/CORP/COEP, X-Frame-Options ...)
 *  2. Permissions-Policy + Cache-Control: no-store on every API response
 *  3. CORS              explicit origin allow-list, never "*", short preflight cache
 *  4. Origin check      state-changing browser requests must come from an allowed origin
 *  5. Method allow-list TRACE / CONNECT / unknown verbs are rejected
 *  6. Rate limiting     100 req/min general, 10 req/min on auth-style endpoints
 *  7. Input hygiene     operator keys, prototype pollution, HPP
 *  8. Structured request log (JSON, no query strings, no tokens)
 */

import crypto from "crypto";
import rateLimit from "express-rate-limit";
import helmet from "helmet";
import cors from "cors";
import hpp from "hpp";
import { Request, Response, NextFunction } from "express";
import { log } from "../lib/log";

// ── Allowed browser origins ──

// Our own production site is always allowed, so a missing or stale FRONTEND_URL can never lock real users out.
const PRODUCTION_ORIGINS = ["https://batkarai.jmadhan.me"];

/** FRONTEND_URL may hold several comma-separated origins (e.g. a staging site). They are added to the production origins. */
export function allowedOrigins(): string[] {
  const fromEnv = (process.env.FRONTEND_URL || "")
    .split(",")
    .map((o) => o.trim().replace(/\/$/, ""))
    .filter(Boolean);
  const local = process.env.NODE_ENV === "production" ? [] : ["http://localhost:3000", "http://localhost:3001"];
  return Array.from(new Set([...PRODUCTION_ORIGINS, ...fromEnv, ...local]));
}

// Server-to-server callers (phone providers, lead webhooks) are authenticated by signature/API key, not by origin.
const NO_ORIGIN_CHECK = ["/api/v1/telephony", "/api/v1/lead-intake"];

// ── Rate limiters ──

const tooMany = (error: string) => ({ error });

/** General: 100 requests per minute per IP. Phone-provider callbacks are signed and come from shared IPs. */
export const globalLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: 100,
  skip: (req) => req.path.startsWith("/api/v1/telephony"),
  standardHeaders: true,
  legacyHeaders: false,
  message: tooMany("Too many requests. Try again later."),
});

/** Sensitive endpoints (login-like, destructive): 10 per minute per IP, failures only for logins. */
export const authLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: 10,
  standardHeaders: true,
  legacyHeaders: false,
  message: tooMany("Too many attempts. Try again in a minute."),
});

/** Lead intake: 60 per minute (webhook flood protection) */
export const leadIntakeLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: 60,
  message: tooMany("Rate limit exceeded for lead intake."),
});

/** Signup: 3 per hour per IP (prevents mass account creation) */
export const signupLimiter = rateLimit({
  windowMs: 60 * 60 * 1000,
  max: 3,
  message: tooMany("Too many signups from this IP. Try again later."),
});

// ── Security headers ──

// The API only returns JSON, so it needs no script/style/image sources at all.
const helmetHeaders = helmet({
  contentSecurityPolicy: {
    useDefaults: false,
    directives: {
      defaultSrc: ["'none'"],
      frameAncestors: ["'none'"],
      baseUri: ["'self'"],
      formAction: ["'self'"],
    },
  },
  hsts: { maxAge: 63072000, includeSubDomains: true, preload: true },
  referrerPolicy: { policy: "strict-origin-when-cross-origin" },
  crossOriginOpenerPolicy: { policy: "same-origin" },
  crossOriginResourcePolicy: { policy: "same-origin" },
  crossOriginEmbedderPolicy: { policy: "require-corp" },
  frameguard: { action: "deny" },
  xXssProtection: false, // sends "0": the legacy XSS auditor is off, CSP does the work
});

export function securityHeaders(req: Request, res: Response, next: NextFunction) {
  res.setHeader("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()");
  res.setHeader("Cache-Control", "no-store, no-cache, must-revalidate");
  res.setHeader("Pragma", "no-cache");
  res.removeHeader("X-Powered-By");
  helmetHeaders(req, res, next);
}

// ── CORS (explicit allow-list) ──

export const corsConfig = cors({
  origin: (origin, callback) => {
    // No Origin header = not a browser (curl, phone provider, health checks). CORS is a browser rule.
    if (!origin) return callback(null, false);
    // Disallowed origins simply get no CORS headers; the browser then blocks the response.
    callback(null, allowedOrigins().includes(origin));
  },
  credentials: true,
  methods: ["GET", "POST", "PATCH", "DELETE"],
  allowedHeaders: ["Content-Type", "Authorization", "X-API-Key", "X-Request-ID"],
  maxAge: 600, // preflight cached 10 minutes
});

/** Reject browser writes from origins we don't know (CSRF defence in depth; auth is a bearer token, not a cookie). */
export function verifyOrigin(req: Request, res: Response, next: NextFunction) {
  if (["GET", "HEAD", "OPTIONS"].includes(req.method)) return next();
  if (NO_ORIGIN_CHECK.some((p) => req.path.startsWith(p))) return next();
  const origin = req.headers.origin;
  if (origin && !allowedOrigins().includes(origin)) {
    log.warn("origin_rejected", { ip: req.ip, path: req.path, origin });
    return res.status(403).json({ error: "Forbidden" });
  }
  next();
}

const ALLOWED_METHODS = new Set(["GET", "HEAD", "POST", "PATCH", "DELETE", "OPTIONS"]);

export function methodAllowList(req: Request, res: Response, next: NextFunction) {
  if (!ALLOWED_METHODS.has(req.method)) {
    res.setHeader("Allow", [...ALLOWED_METHODS].join(", "));
    return res.status(405).json({ error: "Method not allowed" });
  }
  next();
}

// ── HPP (HTTP Parameter Pollution) ──
export const hppProtection = hpp();

// ── Input sanitization ──

/** Strip operator keys ($ne ...) and prototype-pollution keys from bodies; drop odd query keys. */
export function sanitizeInput(req: Request, _res: Response, next: NextFunction) {
  if (req.body && typeof req.body === "object") {
    req.body = deepSanitize(req.body);
  }
  if (req.query && typeof req.query === "object") {
    for (const key of Object.keys(req.query)) {
      if (key.startsWith("$") || key.includes(".")) {
        delete req.query[key];
      }
    }
  }
  next();
}

function deepSanitize(obj: any): any {
  if (Array.isArray(obj)) return obj.map(deepSanitize);
  if (obj !== null && typeof obj === "object") {
    const cleaned: any = {};
    for (const [key, value] of Object.entries(obj)) {
      if (key.startsWith("$") || key === "__proto__" || key === "constructor" || key === "prototype") continue;
      cleaned[key] = deepSanitize(value);
    }
    return cleaned;
  }
  return obj;
}

// ── Request ID + structured access log ──

const REQUEST_ID = /^[A-Za-z0-9-]{8,64}$/;

export function addRequestId(req: Request, res: Response, next: NextFunction) {
  const given = req.headers["x-request-id"];
  const id = typeof given === "string" && REQUEST_ID.test(given) ? given : crypto.randomUUID();
  req.headers["x-request-id"] = id;
  res.setHeader("X-Request-ID", id);
  next();
}

/** One JSON line per request: when, who, what, result. Path only (query strings can carry tokens). */
export function accessLog(req: Request, res: Response, next: NextFunction) {
  const start = Date.now();
  res.on("finish", () => {
    const fields = {
      request_id: req.headers["x-request-id"],
      ip: req.ip,
      user_id: req.authUserId,
      account_id: req.accountId,
      method: req.method,
      path: req.path,
      status: res.statusCode,
      ms: Date.now() - start,
    };
    if (res.statusCode === 401 || res.statusCode === 403) log.warn("access_denied", fields);
    else if (res.statusCode >= 500) log.error("request_failed", fields);
    else log.info("request", fields);
  });
  next();
}
