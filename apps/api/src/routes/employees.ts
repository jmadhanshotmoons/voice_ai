/**
 * Employee (AI Agent) CRUD routes.
 *
 * SECURITY:
 * - All queries filter by req.accountId (set by auth middleware from JWT)
 * - Never accepts account_id from request body (IDOR prevention)
 * - Zod validation strips unknown fields (mass assignment prevention)
 * - Webhook secrets are generated server-side, never client-supplied
 */

import { Router, Request, Response } from "express";
import { z } from "zod";
import { createClient } from "@supabase/supabase-js";
import crypto from "crypto";
import { validate } from "../middleware/validate";

const router = Router();
const supabase = createClient(
  process.env.SUPABASE_URL || "",
  process.env.SUPABASE_SERVICE_KEY || ""
);

const createEmployeeSchema = z.object({
  name: z.string().min(1).max(100),
  language: z.enum(["hi-IN", "te-IN", "ta-IN", "kn-IN", "ml-IN", "mr-IN", "en-IN"]).default("hi-IN"),
  voice_provider: z.enum(["cartesia", "sarvam"]).default("cartesia"),
  voice_id: z.string().default(""),
  voice_tier: z.enum(["standard", "premium"]).default("standard"),
  greeting: z.string().max(500).default(""),
  system_prompt: z.string().max(5000).default(""),
  knowledge_base: z.string().max(10000).default(""),
  capture_fields: z.array(z.string().max(50)).max(20).default(["name", "interest"]),
  mode: z.enum(["instant", "bulk", "inbound"]).default("instant"),
  tools_enabled: z.array(z.string()).default(["capture_field"]),
  max_call_duration_s: z.number().int().min(30).max(1800).default(300),
});

const updateEmployeeSchema = createEmployeeSchema.partial();

// GET /api/v1/employees -- list all for account
router.get("/", async (req: Request, res: Response) => {
  const { data, error } = await supabase
    .from("employees")
    .select("*")
    .eq("account_id", req.accountId!)
    .order("created_at", { ascending: false });

  if (error) return res.status(500).json({ error: error.message });
  res.json({ employees: data });
});

// GET /api/v1/employees/:id
router.get("/:id", async (req: Request, res: Response) => {
  const { data, error } = await supabase
    .from("employees")
    .select("*")
    .eq("id", req.params.id)
    .eq("account_id", req.accountId!) // IDOR protection: always filter by account
    .single();

  if (error || !data) return res.status(404).json({ error: "Employee not found" });
  res.json(data);
});

// POST /api/v1/employees -- create new agent
router.post("/", validate(createEmployeeSchema), async (req: Request, res: Response) => {
  const slug = `${req.body.name.toLowerCase().replace(/[^a-z0-9]/g, "-")}-${crypto.randomBytes(4).toString("hex")}`;
  const webhookSecret = crypto.randomBytes(32).toString("hex");

  const { data, error } = await supabase
    .from("employees")
    .insert({
      ...req.body,
      account_id: req.accountId!, // Server-set, never from body
      slug,
      webhook_secret: webhookSecret,
    })
    .select()
    .single();

  if (error) return res.status(500).json({ error: error.message });
  res.status(201).json(data);
});

// PATCH /api/v1/employees/:id
router.patch("/:id", validate(updateEmployeeSchema), async (req: Request, res: Response) => {
  const { data, error } = await supabase
    .from("employees")
    .update(req.body)
    .eq("id", req.params.id)
    .eq("account_id", req.accountId!) // IDOR protection
    .select()
    .single();

  if (error || !data) return res.status(404).json({ error: "Employee not found" });
  res.json(data);
});

// DELETE /api/v1/employees/:id
router.delete("/:id", async (req: Request, res: Response) => {
  const { error } = await supabase
    .from("employees")
    .delete()
    .eq("id", req.params.id)
    .eq("account_id", req.accountId!); // IDOR protection

  if (error) return res.status(500).json({ error: error.message });
  res.status(204).send();
});

// POST /api/v1/employees/:id/webhook/rotate-secret
router.post("/:id/webhook/rotate-secret", async (req: Request, res: Response) => {
  const newSecret = crypto.randomBytes(32).toString("hex");

  const { data, error } = await supabase
    .from("employees")
    .update({ webhook_secret: newSecret })
    .eq("id", req.params.id)
    .eq("account_id", req.accountId!)
    .select("id, webhook_secret")
    .single();

  if (error || !data) return res.status(404).json({ error: "Employee not found" });
  res.json({ webhook_secret: data.webhook_secret });
});

export default router;
