/**
 * Leads API routes.
 *
 * SECURITY: All queries scoped to req.accountId.
 */

import { Router, Request, Response } from "express";
import { createClient } from "@supabase/supabase-js";

const router = Router();
const supabase = createClient(
  process.env.SUPABASE_URL || "",
  process.env.SUPABASE_SERVICE_KEY || ""
);

// GET /api/v1/leads
router.get("/", async (req: Request, res: Response) => {
  const limit = Math.min(200, parseInt(req.query.limit as string) || 50);
  const offset = parseInt(req.query.offset as string) || 0;
  const outcome = req.query.outcome as string;
  const employeeId = req.query.employee_id as string;

  let query = supabase
    .from("leads")
    .select("*, employees(name), calls(duration_seconds, status, summary, captured_fields)", { count: "exact" })
    .eq("account_id", req.accountId!)
    .order("created_at", { ascending: false })
    .range(offset, offset + limit - 1);

  if (outcome) query = query.eq("outcome", outcome);
  if (employeeId) query = query.eq("employee_id", employeeId);

  const { data, count, error } = await query;
  if (error) return res.status(500).json({ error: error.message });
  res.json({ leads: data, total: count || 0 });
});

// PATCH /api/v1/leads/:id -- update outcome/notes
router.patch("/:id", async (req: Request, res: Response) => {
  const { outcome, notes } = req.body;
  const update: any = {};
  if (outcome !== undefined) update.outcome = outcome;
  if (notes !== undefined) update.notes = notes;

  const { data, error } = await supabase
    .from("leads")
    .update(update)
    .eq("id", req.params.id)
    .eq("account_id", req.accountId!)
    .select()
    .single();

  if (error || !data) return res.status(404).json({ error: "Lead not found" });
  res.json(data);
});

// GET /api/v1/leads/summary
router.get("/summary", async (req: Request, res: Response) => {
  const { data, error } = await supabase
    .from("leads")
    .select("outcome")
    .eq("account_id", req.accountId!);

  if (error) return res.status(500).json({ error: error.message });

  const summary = {
    total: data?.length || 0,
    interested: data?.filter((l) => l.outcome === "interested").length || 0,
    not_interested: data?.filter((l) => l.outcome === "not_interested").length || 0,
    callback: data?.filter((l) => l.outcome === "callback").length || 0,
    no_answer: data?.filter((l) => l.outcome === "no_answer").length || 0,
    unclassified: data?.filter((l) => !l.outcome || l.outcome === "").length || 0,
  };

  res.json(summary);
});

export default router;
