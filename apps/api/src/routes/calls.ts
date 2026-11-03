/**
 * Call log routes.
 *
 * SECURITY:
 * - All queries scoped to req.accountId (IDOR prevention)
 * - Recording URLs are signed with expiry (prevent URL guessing)
 * - Pagination limits enforced (prevent data dump)
 */

import { Router, Request, Response } from "express";
import { createClient } from "@supabase/supabase-js";
import { z } from "zod";
import rateLimit from "express-rate-limit";
import { validate } from "../middleware/validate";
import { placeCall, normalizePhone, allowedPrefixes, provider } from "../lib/telephony";
import { signTicket } from "../lib/ticket";
import { log } from "../lib/log";

const router = Router();
const supabase = createClient(
  process.env.SUPABASE_URL || "",
  process.env.SUPABASE_SERVICE_KEY || ""
);


// ── Outbound phone call ──────────────────────────────────────────────
const MIN_CREDITS_TO_CALL = 5;
const MAX_ACTIVE_CALLS = 3;

const outboundLimiter = rateLimit({
  windowMs: 60_000,
  max: 5,
  keyGenerator: (req) => (req as Request).accountId || "anon",
  message: { error: "Too many call requests. Wait a minute and try again." },
});

const outboundSchema = z.object({
  employee_id: z.string().uuid(),
  phone_number: z.string().min(10).max(20),
  lead_id: z.string().uuid().optional(),
  // The caller confirms they have permission to call this number (consent / DND rules).
  consent: z.literal(true),
});

// POST /api/v1/calls/outbound -- ring a phone with an AI employee
router.post("/outbound", outboundLimiter, validate(outboundSchema), async (req: Request, res: Response) => {
  const phone = normalizePhone(req.body.phone_number);
  if (!phone) return res.status(400).json({ error: "Enter a valid phone number, e.g. 98765 43210" });
  if (!allowedPrefixes().some((p) => phone.startsWith(p))) {
    return res.status(400).json({ error: `Calls to this country are not enabled (${allowedPrefixes().join(", ")} only)` });
  }

  // Employee must belong to this account (IDOR protection)
  const { data: employee } = await supabase
    .from("employees")
    .select("id, is_active")
    .eq("id", req.body.employee_id)
    .eq("account_id", req.accountId!)
    .single();
  if (!employee) return res.status(404).json({ error: "Employee not found" });
  if (!employee.is_active) return res.status(400).json({ error: "This employee is switched off" });

  const { data: account } = await supabase.from("accounts").select("credits").eq("id", req.accountId!).single();
  if (!account || Number(account.credits) < MIN_CREDITS_TO_CALL) {
    return res.status(402).json({ error: `At least Rs ${MIN_CREDITS_TO_CALL} of credits is needed to place a call` });
  }

  const since = new Date(Date.now() - 15 * 60_000).toISOString();
  const { count: active } = await supabase
    .from("calls")
    .select("id", { count: "exact", head: true })
    .eq("account_id", req.accountId!)
    .in("status", ["pending", "ringing", "connected"])
    .gte("created_at", since);
  if ((active || 0) >= MAX_ACTIVE_CALLS) {
    return res.status(429).json({ error: "Too many calls in progress. Wait for one to finish." });
  }

  const { data: call, error: insErr } = await supabase
    .from("calls")
    .insert({
      account_id: req.accountId!, // server-set, never from body
      employee_id: employee.id,
      phone_number: phone,
      direction: "outbound",
      status: "pending",
      lead_id: req.body.lead_id || null,
      provider: provider(),
    })
    .select("id")
    .single();
  if (insErr || !call) return res.status(500).json({ error: "Could not create the call" });

  try {
    const placed = await placeCall(call.id, phone);
    await supabase
      .from("calls")
      .update({ status: "ringing", provider_call_sid: placed.sid })
      .eq("id", call.id);
    res.status(201).json({ call_id: call.id, status: "ringing", provider: placed.provider });
  } catch (err: any) {
    await supabase.from("calls").update({ status: "failed" }).eq("id", call.id);
    log.error("outbound_call_failed", { error: err.message });
    res.status(502).json({ error: err.message || "The phone provider rejected the call" });
  }
});

// POST /api/v1/calls/web-ticket -- short-lived ticket to open a browser test call to the voice server
const webTicketSchema = z.object({ employee_id: z.string().uuid() });

router.post("/web-ticket", outboundLimiter, validate(webTicketSchema), async (req: Request, res: Response) => {
  // Employee must belong to this account (IDOR protection)
  const { data: employee } = await supabase
    .from("employees")
    .select("id")
    .eq("id", req.body.employee_id)
    .eq("account_id", req.accountId!)
    .single();
  if (!employee) return res.status(404).json({ error: "Employee not found" });
  if (!process.env.WEBHOOK_SECRET) return res.status(503).json({ error: "Calling is not configured" });
  res.json({ ticket: signTicket(`test-${employee.id}`) });
});

// GET /api/v1/calls -- list calls with pagination
router.get("/", async (req: Request, res: Response) => {
  const page = Math.max(1, parseInt(req.query.page as string) || 1);
  const limit = Math.min(100, Math.max(1, parseInt(req.query.limit as string) || 20));
  const offset = (page - 1) * limit;
  const employeeId = req.query.employee_id as string;
  const status = req.query.status as string;

  let query = supabase
    .from("calls")
    .select("*, employees(name, language)", { count: "exact" })
    .eq("account_id", req.accountId!)
    .order("created_at", { ascending: false })
    .range(offset, offset + limit - 1);

  if (employeeId) query = query.eq("employee_id", employeeId);
  if (status) query = query.eq("status", status);

  const { data, count, error } = await query;
  if (error) return res.status(500).json({ error: error.message });

  res.json({
    calls: data,
    pagination: { page, limit, total: count || 0, pages: Math.ceil((count || 0) / limit) },
  });
});

// GET /api/v1/calls/:id -- single call detail
router.get("/:id", async (req: Request, res: Response) => {
  const { data, error } = await supabase
    .from("calls")
    .select("*, employees(name, language)")
    .eq("id", req.params.id)
    .eq("account_id", req.accountId!) // IDOR protection
    .single();

  if (error || !data) return res.status(404).json({ error: "Call not found" });
  res.json(data);
});

// GET /api/v1/calls/summary -- aggregate stats
router.get("/summary/stats", async (req: Request, res: Response) => {
  const days = Math.min(90, parseInt(req.query.days as string) || 30);
  const since = new Date(Date.now() - days * 86400000).toISOString();

  const { data, error } = await supabase
    .from("calls")
    .select("status, duration_seconds, credits_used")
    .eq("account_id", req.accountId!)
    .gte("created_at", since);

  if (error) return res.status(500).json({ error: error.message });

  const stats = {
    total_calls: data?.length || 0,
    completed: data?.filter((c) => c.status === "completed").length || 0,
    total_duration_min: Math.round((data?.reduce((s, c) => s + c.duration_seconds, 0) || 0) / 60),
    total_credits: data?.reduce((s, c) => s + c.credits_used, 0) || 0,
  };

  res.json(stats);
});

export default router;
