/**
 * API Server Entry Point
 *
 * SECURITY HARDENING (lessons from Outpero assessment):
 * - Rate limiting on all endpoints
 * - Strict CORS (Outpero had wildcard on some services)
 * - Auth on every route (Outpero admin routes used same JWT as users)
 * - Input sanitization (NoSQL injection prevention)
 * - No version/stack leaking in headers
 * - Request size limits (prevents DoS)
 */

import "./env";

import express from "express";
import { createClient } from "@supabase/supabase-js";
import Redis from "ioredis";

import {
  globalLimiter,
  securityHeaders,
  corsConfig,
  hppProtection,
  sanitizeInput,
  addRequestId,
  accessLog,
  verifyOrigin,
  methodAllowList,
} from "./middleware/security";
import { log } from "./lib/log";
import { requireAuth, requireAdmin } from "./middleware/auth";
import employeeRoutes from "./routes/employees";
import callRoutes from "./routes/calls";
import billingRoutes from "./routes/billing";
import leadIntakeRoutes from "./routes/lead-intake";
import campaignRoutes from "./routes/campaigns";
import leadRoutes from "./routes/leads";
import numberRoutes from "./routes/numbers";
import telephonyWebhookRoutes from "./routes/telephony-webhooks";
import accountRoutes from "./routes/account";

const app = express();
// Behind one reverse proxy (Render / Cloudflare tunnel): use the real client IP for rate limits
app.set("trust proxy", 1);
const PORT = process.env.PORT || 3001;

// ── Global Security Middleware (order matters) ──
app.disable("x-powered-by"); // no framework fingerprint
app.use(addRequestId);
app.use(accessLog);
app.use(methodAllowList);
app.use(securityHeaders);
app.use(corsConfig);
app.use(verifyOrigin);
app.use(hppProtection);
app.use(express.json({ limit: "1mb" })); // Prevent large payload DoS
app.use(express.urlencoded({ extended: false, limit: "1mb" }));
app.use(sanitizeInput);
app.use(globalLimiter);

// ── External Clients ──
export const supabase = createClient(
  process.env.SUPABASE_URL || "",
  process.env.SUPABASE_SERVICE_KEY || ""
);

export const redis = new Redis(process.env.REDIS_URL || "redis://localhost:6379");

// ── Health (unauthenticated) ──
app.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

// ── Security contact (RFC 9116) ──
app.get("/.well-known/security.txt", (_req, res) => {
  res.type("text/plain").send(
    [
      "Contact: mailto:jmadhan.shotmoons@gmail.com",
      "Expires: 2027-12-31T00:00:00.000Z",
      "Preferred-Languages: en",
      "",
    ].join("\n")
  );
});

// ── Authenticated Routes ──
app.use("/api/v1/employees", requireAuth, employeeRoutes);
app.use("/api/v1/calls", requireAuth, callRoutes);
app.use("/api/v1/billing", requireAuth, billingRoutes);
app.use("/api/v1/campaigns", requireAuth, campaignRoutes);
app.use("/api/v1/leads", requireAuth, leadRoutes);
app.use("/api/v1/numbers", requireAuth, numberRoutes);
app.use("/api/v1/account", requireAuth, accountRoutes);

// ── Public Routes (API-key or webhook auth) ──
app.use("/api/v1/lead-intake", leadIntakeRoutes);
app.use("/api/v1/telephony", telephonyWebhookRoutes);

// ── 404 catch-all (don't leak route info) ──
app.use((_req, res) => {
  res.status(404).json({ error: "Not found" });
});

// ── Global error handler (never leak stack traces, SQL errors or paths) ──
app.use((err: any, req: any, res: any, _next: any) => {
  if (err?.type === "entity.too.large") return res.status(413).json({ error: "Request too large" });
  if (err?.type === "entity.parse.failed") return res.status(400).json({ error: "Invalid request body" });
  log.error("unhandled_error", { request_id: req.headers["x-request-id"], path: req.path, error: String(err?.message || err) });
  res.status(500).json({ error: "Something went wrong" });
});

app.listen(PORT, () => {
  log.info("api_started", { port: Number(PORT) });
});

export default app;
