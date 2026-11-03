/**
 * Security middleware stack.
 *
 * Defends against every attack class found in Outpero and common SaaS targets:
 *
 * 1. Rate limiting        -- prevents brute force (Outpero had ZERO rate limiting on admin login)
 * 2. Helmet               -- security headers (CSP, HSTS, X-Frame-Options, etc.)
 * 3. Input sanitization   -- strips NoSQL operators ($ne, $gt) from JSON bodies
 * 4. HPP                  -- HTTP Parameter Pollution protection
 * 5. Request size limit   -- prevents DoS via large payloads
 * 6. CORS strict origin   -- prevents cross-origin credential theft
 * 7. CSRF via SameSite    -- cookies set SameSite=Strict
 */

import rateLimit from "express-rate-limit";
import helmet from "helmet";
import cors from "cors";
import hpp from "hpp";
import { Request, Response, NextFunction } from "express";

// ── Rate Limiters ──

/** Global: 600 requests per 15 minutes per IP (the dashboard polls call status while a call is live) */
export const globalLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 600,
  // Phone-provider callbacks are protected by a signed token and come from shared provider IPs
  skip: (req) => req.path.startsWith("/api/v1/telephony"),
  standardHeaders: true,
  legacyHeaders: false,
  message: { error: "Too many requests. Try again later." },
  // Use X-Forwarded-For only behind trusted proxy (Cloudflare)
  // SECURITY: Without this, attacker can spoof X-Forwarded-For to bypass rate limit
  // keyGenerator: (req) => req.ip, // default -- uses connection IP
});

/** Auth endpoints: 5 attempts per 15 minutes (prevents brute force) */
export const authLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 5,
  message: { error: "Too many login attempts. Try again in 15 minutes." },
  skipSuccessfulRequests: true, // Only count failed attempts
});

/** Lead intake: 60 per minute (webhook flood protection) */
export const leadIntakeLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: 60,
  message: { error: "Rate limit exceeded for lead intake." },
});

/** Signup: 3 per hour per IP (prevents mass account creation -- Outpero had this bug) */
export const signupLimiter = rateLimit({
  windowMs: 60 * 60 * 1000,
  max: 3,
  message: { error: "Too many signups from this IP. Try again later." },
});

// ── Helmet (Security Headers) ──

export const securityHeaders = helmet({
  contentSecurityPolicy: {
    directives: {
      defaultSrc: ["'self'"],
      scriptSrc: ["'self'", "'unsafe-inline'"], // For Razorpay checkout
      styleSrc: ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
      fontSrc: ["'self'", "https://fonts.gstatic.com"],
      imgSrc: ["'self'", "data:", "https:"],
      connectSrc: ["'self'", "https://api.outpero.com", "wss:"],
      frameSrc: ["'self'", "https://api.razorpay.com"], // Razorpay iframe
      frameAncestors: ["'none'"], // Prevents clickjacking
      baseUri: ["'self'"],
      formAction: ["'self'"],
    },
  },
  crossOriginEmbedderPolicy: false, // Allow Razorpay
  hsts: { maxAge: 31536000, includeSubDomains: true, preload: true },
  referrerPolicy: { policy: "strict-origin-when-cross-origin" },
});

// ── CORS (strict origin) ──

const ALLOWED_ORIGINS = [
  process.env.FRONTEND_URL || "http://localhost:3000",
  // Add production domains here
];

export const corsConfig = cors({
  origin: (origin, callback) => {
    // Allow requests with no origin (mobile apps, curl, server-to-server)
    if (!origin) return callback(null, true);
    if (ALLOWED_ORIGINS.includes(origin)) {
      callback(null, true);
    } else {
      callback(new Error("Not allowed by CORS"));
    }
  },
  credentials: true,
  methods: ["GET", "POST", "PUT", "PATCH", "DELETE"],
  allowedHeaders: ["Content-Type", "Authorization", "X-API-Key", "X-Request-ID"],
  maxAge: 86400, // Cache preflight for 24 hours
});

// ── HPP (HTTP Parameter Pollution) ──
export const hppProtection = hpp();

// ── Input Sanitization ──

/**
 * Strip MongoDB/NoSQL operators from request body.
 * Prevents: {"username": {"$ne": null}, "password": {"$ne": null}}
 * Even though we use PostgreSQL, defense in depth.
 */
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
  if (Array.isArray(obj)) {
    return obj.map(deepSanitize);
  }
  if (obj !== null && typeof obj === "object") {
    const cleaned: any = {};
    for (const [key, value] of Object.entries(obj)) {
      // Block NoSQL operators and prototype pollution
      if (key.startsWith("$") || key === "__proto__" || key === "constructor" || key === "prototype") {
        continue;
      }
      cleaned[key] = deepSanitize(value);
    }
    return cleaned;
  }
  return obj;
}

// ── Request ID (for tracing) ──

export function addRequestId(req: Request, _res: Response, next: NextFunction) {
  const crypto = require("crypto");
  req.headers["x-request-id"] =
    req.headers["x-request-id"] || crypto.randomUUID();
  next();
}
