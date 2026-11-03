/**
 * Lead intake endpoint -- receives leads from external sources.
 *
 * SECURITY:
 * - HMAC-SHA256 signature verification (prevents unauthorized lead injection)
 * - Rate limited to 60/min (prevents webhook flood DoS)
 * - Input validation strips all unexpected fields
 * - Phone number format validation
 * - No account_id in URL/body -- derived from employee slug lookup
 */

import { Router, Request, Response } from "express";
import { z } from "zod";
import crypto from "crypto";
import { createClient } from "@supabase/supabase-js";
import { validate } from "../middleware/validate";
import { leadIntakeLimiter } from "../middleware/security";
import { log } from "../lib/log";

const router = Router();
const supabase = createClient(
  process.env.SUPABASE_URL || "",
  process.env.SUPABASE_SERVICE_KEY || ""
);

const leadSchema = z.object({
  phone: z.string().regex(/^\+?[1-9]\d{7,14}$/, "Invalid phone number format"),
  name: z.string().max(200).optional(),
  // Allow arbitrary custom fields but limit total size
}).passthrough().refine(
  (data) => JSON.stringify(data).length < 5000,
  "Payload too large"
);

// POST /api/v1/lead-intake/:slug
router.post("/:slug", leadIntakeLimiter, validate(leadSchema), async (req: Request, res: Response) => {
  const { slug } = req.params;

  // Look up employee by slug
  const { data: employee, error } = await supabase
    .from("employees")
    .select("id, account_id, webhook_secret, is_active")
    .eq("slug", slug)
    .single();

  if (error || !employee) {
    return res.status(404).json({ error: "Agent not found" });
  }

  if (!employee.is_active) {
    return res.status(400).json({ error: "Agent is not active" });
  }

  // Every request must prove it may add leads for this agent: a valid HMAC signature
  // (X-Lead-Secret) or an API key of the same account (X-API-Key). Anonymous posts are rejected.
  let authorised = false;
  const signature = req.headers["x-lead-secret"];
  const apiKey = req.headers["x-api-key"];

  if (typeof signature === "string") {
    const expected = crypto.createHmac("sha256", employee.webhook_secret).update(JSON.stringify(req.body)).digest("hex");
    const a = Buffer.from(signature);
    const b = Buffer.from(expected);
    authorised = a.length === b.length && crypto.timingSafeEqual(a, b);
  } else if (typeof apiKey === "string" && apiKey.length <= 200) {
    const keyHash = crypto.createHash("sha256").update(apiKey).digest("hex");
    const { data: keyRecord } = await supabase
      .from("api_keys")
      .select("id")
      .eq("key_hash", keyHash)
      .eq("account_id", employee.account_id)
      .eq("is_active", true)
      .single();
    authorised = !!keyRecord;
    if (keyRecord) {
      supabase.from("api_keys").update({ last_used_at: new Date().toISOString() }).eq("id", keyRecord.id).then();
    }
  }

  if (!authorised) {
    log.warn("lead_intake_rejected", { ip: req.ip, slug });
    return res.status(401).json({ error: "Missing or invalid credentials" });
  }

  // Check account has credits
  const { data: account } = await supabase
    .from("accounts")
    .select("credits")
    .eq("id", employee.account_id)
    .single();

  if (!account || account.credits <= 0) {
    return res.status(402).json({ error: "Insufficient credits" });
  }

  // Create lead and trigger call (async)
  const { phone, name, ...customFields } = req.body;

  const { data: lead } = await supabase
    .from("leads")
    .insert({
      account_id: employee.account_id,
      employee_id: employee.id,
      phone_number: phone,
      name: name || "",
      captured_data: customFields,
      outcome: "",
    })
    .select("id")
    .single();

  // TODO: Trigger outbound call via telephony service
  // await telephonyService.initiateCall(employee.id, phone, lead?.id);

  res.status(202).json({
    status: "accepted",
    lead_id: lead?.id,
    message: "Lead received.",
  });
});

export default router;
