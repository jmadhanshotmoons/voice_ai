/**
 * Campaign routes -- create, list, manage bulk calling campaigns.
 *
 * SECURITY:
 * - All queries scoped to req.accountId
 * - Contact CSV parsed server-side with size limits
 * - Campaign launch checks credit balance before starting
 */

import { Router, Request, Response } from "express";
import { z } from "zod";
import { createClient } from "@supabase/supabase-js";
import { validate } from "../middleware/validate";

const router = Router();
const supabase = createClient(
  process.env.SUPABASE_URL || "",
  process.env.SUPABASE_SERVICE_KEY || ""
);

const createCampaignSchema = z.object({
  name: z.string().min(1).max(200),
  employee_id: z.string().uuid(),
  calling_hours: z.object({
    start: z.string().regex(/^\d{2}:\d{2}$/),
    end: z.string().regex(/^\d{2}:\d{2}$/),
  }).default({ start: "09:00", end: "18:00" }),
  max_retries: z.number().int().min(0).max(5).default(3),
  contacts: z.array(z.object({
    phone_number: z.string().min(10).max(15),
    name: z.string().max(200).default(""),
    custom_fields: z.record(z.string()).default({}),
  })).min(1).max(10000),
});

// GET /api/v1/campaigns
router.get("/", async (req: Request, res: Response) => {
  const { data, error } = await supabase
    .from("campaigns")
    .select("*, employees(name)")
    .eq("account_id", req.accountId!)
    .order("created_at", { ascending: false });

  if (error) return res.status(500).json({ error: error.message });
  res.json({ campaigns: data });
});

// POST /api/v1/campaigns
router.post("/", validate(createCampaignSchema), async (req: Request, res: Response) => {
  const { contacts, ...campaignData } = req.body;

  // Verify employee belongs to this account
  const { data: emp } = await supabase
    .from("employees")
    .select("id")
    .eq("id", campaignData.employee_id)
    .eq("account_id", req.accountId!)
    .single();

  if (!emp) return res.status(404).json({ error: "Employee not found" });

  // Check credits (rough estimate: 2 min avg per contact at Rs 5/min)
  const { data: account } = await supabase
    .from("accounts")
    .select("credits")
    .eq("id", req.accountId!)
    .single();

  const estimatedCost = contacts.length * 10; // Rs 10 per contact estimate
  if (!account || account.credits < estimatedCost) {
    return res.status(402).json({
      error: `Insufficient credits. Estimated cost: Rs ${estimatedCost}. Your balance: Rs ${account?.credits || 0}`,
    });
  }

  // Create campaign
  const { data: campaign, error } = await supabase
    .from("campaigns")
    .insert({
      ...campaignData,
      account_id: req.accountId!,
      total_contacts: contacts.length,
      status: "active",
    })
    .select()
    .single();

  if (error || !campaign) return res.status(500).json({ error: error?.message || "Failed" });

  // Insert contacts in batches of 500
  for (let i = 0; i < contacts.length; i += 500) {
    const batch = contacts.slice(i, i + 500).map((c: any) => ({
      campaign_id: campaign.id,
      phone_number: c.phone_number,
      name: c.name,
      custom_fields: c.custom_fields,
      status: "pending",
    }));

    await supabase.from("campaign_contacts").insert(batch);
  }

  res.status(201).json(campaign);
});

// POST /api/v1/campaigns/:id/pause
router.post("/:id/pause", async (req: Request, res: Response) => {
  const { data, error } = await supabase
    .from("campaigns")
    .update({ status: "paused" })
    .eq("id", req.params.id)
    .eq("account_id", req.accountId!)
    .select()
    .single();

  if (error || !data) return res.status(404).json({ error: "Campaign not found" });
  res.json(data);
});

// POST /api/v1/campaigns/:id/resume
router.post("/:id/resume", async (req: Request, res: Response) => {
  const { data, error } = await supabase
    .from("campaigns")
    .update({ status: "active" })
    .eq("id", req.params.id)
    .eq("account_id", req.accountId!)
    .eq("status", "paused")
    .select()
    .single();

  if (error || !data) return res.status(404).json({ error: "Campaign not found or not paused" });
  res.json(data);
});

export default router;
