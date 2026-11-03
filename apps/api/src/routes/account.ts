/**
 * Account routes: profile, API keys, right to delete.
 *
 * SECURITY: the account id always comes from the session, never from the request.
 * API keys are shown once and stored only as a SHA-256 hash (keys carry 256 bits of entropy, so a fast hash is fine).
 * Deleting an account is irreversible, so the caller must re-enter their password and type DELETE.
 */

import crypto from "crypto";
import { Router, Request, Response } from "express";
import { createClient } from "@supabase/supabase-js";
import { z } from "zod";
import { validate } from "../middleware/validate";
import { authLimiter } from "../middleware/security";
import { log } from "../lib/log";

const router = Router();
const supabase = createClient(process.env.SUPABASE_URL || "", process.env.SUPABASE_SERVICE_KEY || "");

// ── Profile ──────────────────────────────────────────────────────────

const profileSchema = z.object({
  company_name: z.string().trim().max(200).optional(),
  phone: z.string().trim().max(20).regex(/^[+0-9 ()-]*$/, "Use digits, spaces and + only").optional(),
});

// GET /api/v1/account/profile
router.get("/profile", async (req: Request, res: Response) => {
  const { data } = await supabase
    .from("accounts")
    .select("email, company_name, phone, plan, credits")
    .eq("id", req.accountId!)
    .single();
  if (!data) return res.status(404).json({ error: "Account not found" });
  res.json(data);
});

// PATCH /api/v1/account/profile
router.patch("/profile", validate(profileSchema), async (req: Request, res: Response) => {
  const update: Record<string, string> = {};
  if (req.body.company_name !== undefined) update.company_name = req.body.company_name;
  if (req.body.phone !== undefined) update.phone = req.body.phone;
  if (!Object.keys(update).length) return res.status(400).json({ error: "Nothing to update" });
  const { error } = await supabase.from("accounts").update(update).eq("id", req.accountId!);
  if (error) return res.status(500).json({ error: "Could not save your profile" });
  res.json({ saved: true });
});

// ── API keys ─────────────────────────────────────────────────────────

const MAX_KEYS = 10;
const keySchema = z.object({ name: z.string().trim().min(1).max(60).default("Default") });

// GET /api/v1/account/api-keys
router.get("/api-keys", async (req: Request, res: Response) => {
  const { data } = await supabase
    .from("api_keys")
    .select("id, name, key_prefix, last_used_at, created_at")
    .eq("account_id", req.accountId!)
    .eq("is_active", true)
    .order("created_at", { ascending: false })
    .limit(MAX_KEYS);
  res.json({ keys: data || [] });
});

// POST /api/v1/account/api-keys -- the full key is returned once, never again
router.post("/api-keys", authLimiter, validate(keySchema), async (req: Request, res: Response) => {
  const { count } = await supabase
    .from("api_keys")
    .select("id", { count: "exact", head: true })
    .eq("account_id", req.accountId!)
    .eq("is_active", true);
  if ((count || 0) >= MAX_KEYS) return res.status(400).json({ error: `You can have up to ${MAX_KEYS} active keys. Revoke one first.` });

  const key = "bk_" + crypto.randomBytes(32).toString("hex");
  const { data, error } = await supabase
    .from("api_keys")
    .insert({
      account_id: req.accountId!,
      name: req.body.name,
      key_hash: crypto.createHash("sha256").update(key).digest("hex"),
      key_prefix: key.slice(0, 11),
    })
    .select("id, name, key_prefix, created_at")
    .single();
  if (error || !data) return res.status(500).json({ error: "Could not create the key" });
  log.info("api_key_created", { account_id: req.accountId, key_id: data.id });
  res.status(201).json({ ...data, key });
});

// DELETE /api/v1/account/api-keys/:id -- revoke
router.delete("/api-keys/:id", async (req: Request, res: Response) => {
  if (!/^[0-9a-f-]{36}$/i.test(req.params.id)) return res.status(400).json({ error: "Invalid key id" });
  const { data } = await supabase
    .from("api_keys")
    .update({ is_active: false })
    .eq("id", req.params.id)
    .eq("account_id", req.accountId!)
    .select("id");
  if (!data?.length) return res.status(404).json({ error: "Key not found" });
  log.info("api_key_revoked", { account_id: req.accountId, key_id: req.params.id });
  res.json({ revoked: true });
});

// ── Delete account ───────────────────────────────────────────────────

const deleteSchema = z.object({
  password: z.string().min(1).max(200),
  confirm: z.literal("DELETE"),
});

// DELETE /api/v1/account -- permanently remove the account and all its data
router.delete("/", authLimiter, validate(deleteSchema), async (req: Request, res: Response) => {
  const email = req.authEmail;
  if (!email) return res.status(400).json({ error: "This account cannot be deleted here" });

  // Re-authenticate with a throw-away client so the service client's session is never touched
  const verifier = createClient(process.env.SUPABASE_URL || "", process.env.SUPABASE_SERVICE_KEY || "", {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const { error: pwError } = await verifier.auth.signInWithPassword({ email, password: req.body.password });
  if (pwError) {
    log.warn("account_delete_bad_password", { ip: req.ip, account_id: req.accountId });
    return res.status(401).json({ error: "Password is incorrect" });
  }

  const { error: dataError } = await supabase.rpc("delete_account_data", { p_account_id: req.accountId });
  if (dataError) {
    log.error("account_delete_failed", { account_id: req.accountId, error: dataError.message });
    return res.status(500).json({ error: "Could not delete the account. Please contact support." });
  }
  const { error: authError } = await supabase.auth.admin.deleteUser(req.authUserId!);
  if (authError) log.error("auth_user_delete_failed", { account_id: req.accountId, error: authError.message });

  log.info("account_deleted", { account_id: req.accountId });
  res.json({ deleted: true });
});

export default router;
