/**
 * Account routes: right to delete.
 *
 * SECURITY: deleting an account is irreversible, so the caller must re-enter their password
 * (fresh proof of identity) and type DELETE. The account id always comes from the session.
 */

import { Router, Request, Response } from "express";
import { createClient } from "@supabase/supabase-js";
import { z } from "zod";
import { validate } from "../middleware/validate";
import { authLimiter } from "../middleware/security";
import { log } from "../lib/log";

const router = Router();
const supabase = createClient(process.env.SUPABASE_URL || "", process.env.SUPABASE_SERVICE_KEY || "");

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
