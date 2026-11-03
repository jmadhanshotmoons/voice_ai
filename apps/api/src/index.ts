/**
 * API Server Entry Point
 *
 * SECURITY HARDENING (lessons from Outpero assessment):
 * - Rate limiting on ALL endpoints (Outpero had zero)
 * - Strict CORS (Outpero had wildcard on some services)
 * - Auth on every route (Outpero admin routes used same JWT as users)
 * - Input sanitization (NoSQL injection prevention)
 * - No version/stack leaking in headers
 * - Request size limits (prevents DoS)
 */

import "./env";

import express from "express";
import morgan from "morgan";
import { createClient } from "@supabase/supabase-js";
import Redis from "ioredis";

import {
  globalLimiter,
  securityHeaders,
  corsConfig,
  hppProtection,
  sanitizeInput,
  addRequestId,
} from "./middleware/security";
import { requireAuth, requireAdmin } from "./middleware/auth";
import employeeRoutes from "./routes/employees";
import callRoutes from "./routes/calls";
import billingRoutes from "./routes/billing";
import leadIntakeRoutes from "./routes/lead-intake";
import campaignRoutes from "./routes/campaigns";
import leadRoutes from "./routes/leads";
import numberRoutes from "./routes/numbers";
import telephonyWebhookRoutes from "./routes/telephony-webhooks";

const app = express();
// Behind one reverse proxy (Render / Cloudflare tunnel): use the real client IP for rate limits
app.set("trust proxy", 1);
const PORT = process.env.PORT || 3001;

// ── Global Security Middleware (order matters) ──
app.use(securityHeaders);
app.use(corsConfig);
app.use(hppProtection);
app.use(addRequestId);
app.use(express.json({ limit: "1mb" })); // Prevent large payload DoS
app.use(express.urlencoded({ extended: false, limit: "1mb" }));
app.use(sanitizeInput);
app.use(globalLimiter);
app.use(morgan("short"));

// Remove Express fingerprint header (prevents version disclosure)
app.disable("x-powered-by");

// ── External Clients ──
export const supabase = createClient(
  process.env.SUPABASE_URL || "",
  process.env.SUPABASE_SERVICE_KEY || ""
);

export const redis = new Redis(process.env.REDIS_URL || "redis://localhost:6379");

// ── Health (unauthenticated) ──
app.get("/health", (_req, res) => {
  res.json({ ok: true, time: new Date().toISOString() });
});

// ── Authenticated Routes ──
app.use("/api/v1/employees", requireAuth, employeeRoutes);
app.use("/api/v1/calls", requireAuth, callRoutes);
app.use("/api/v1/billing", requireAuth, billingRoutes);
app.use("/api/v1/campaigns", requireAuth, campaignRoutes);
app.use("/api/v1/leads", requireAuth, leadRoutes);
app.use("/api/v1/numbers", requireAuth, numberRoutes);

// ── Public Routes (API-key or webhook auth) ──
app.use("/api/v1/lead-intake", leadIntakeRoutes);
app.use("/api/v1/telephony", telephonyWebhookRoutes);

// ── 404 catch-all (don't leak route info) ──
app.use((_req, res) => {
  res.status(404).json({ error: "Not found" });
});

// ── Global error handler (don't leak stack traces) ──
app.use((err: any, _req: any, res: any, _next: any) => {
  console.error("Unhandled error:", err.message);
  // SECURITY: Never send stack trace to client in production
  res.status(500).json({
    error: process.env.NODE_ENV === "development" ? err.message : "Internal server error",
  });
});

app.listen(PORT, () => {
  console.log(`API server running on port ${PORT}`);
});

export default app;
