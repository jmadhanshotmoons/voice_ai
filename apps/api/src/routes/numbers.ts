/**
 * Phone numbers API routes.
 *
 * SECURITY:
 * - Numbers scoped to account
 * - Purchase requires credit check
 * - Number release is soft-delete
 */

import { Router, Request, Response } from "express";
import { z } from "zod";
import { createClient } from "@supabase/supabase-js";
import { validate } from "../middleware/validate";
import { RATES } from "../types";

const router = Router();
const supabase = createClient(
  process.env.SUPABASE_URL || "",
  process.env.SUPABASE_SERVICE_KEY || ""
);

// GET /api/v1/numbers
router.get("/", async (req: Request, res: Response) => {
  const { data, error } = await supabase
    .from("phone_numbers")
    .select("*, employees(name)")
    .eq("account_id", req.accountId!)
    .order("created_at", { ascending: false });

  if (error) return res.status(500).json({ error: error.message });
  res.json({ numbers: data });
});

// POST /api/v1/numbers/purchase
const purchaseSchema = z.object({
  channels: z.number().int().min(1).max(50).default(1),
});

router.post("/purchase", validate(purchaseSchema), async (req: Request, res: Response) => {
  const { channels } = req.body;
  const cost = RATES.number_monthly * channels;

  // Check credits
  const { data: account } = await supabase
    .from("accounts")
    .select("credits")
    .eq("id", req.accountId!)
    .single();

  if (!account || account.credits < cost) {
    return res.status(402).json({
      error: `Insufficient credits. Need Rs ${cost} for ${channels} channel(s). Balance: Rs ${account?.credits || 0}`,
    });
  }

  // Deduct credits
  const { data: deductResult } = await supabase.rpc("deduct_credits", {
    p_account_id: req.accountId!,
    p_amount: cost,
    p_type: "number_rental",
    p_description: `Phone number rental: ${channels} channel(s)`,
  });

  if (!deductResult?.success) {
    return res.status(402).json({ error: deductResult?.error || "Failed to deduct" });
  }

  // Create number record (actual Exotel provisioning would happen here)
  const { data: number, error } = await supabase
    .from("phone_numbers")
    .insert({
      account_id: req.accountId!,
      number: `+91${Math.floor(7000000000 + Math.random() * 2999999999)}`, // Placeholder
      provider: "exotel",
      channels,
      monthly_cost: cost,
      is_active: true,
    })
    .select()
    .single();

  if (error) return res.status(500).json({ error: error.message });
  res.status(201).json({ number, credits_deducted: cost, new_balance: deductResult.balance });
});

// POST /api/v1/numbers/:id/add-channel
router.post("/:id/add-channel", async (req: Request, res: Response) => {
  const { data: num } = await supabase
    .from("phone_numbers")
    .select("*")
    .eq("id", req.params.id)
    .eq("account_id", req.accountId!)
    .single();

  if (!num) return res.status(404).json({ error: "Number not found" });

  const cost = RATES.number_monthly;

  const { data: deductResult } = await supabase.rpc("deduct_credits", {
    p_account_id: req.accountId!,
    p_amount: cost,
    p_type: "number_rental",
    p_description: `Add channel to ${num.number}`,
  });

  if (!deductResult?.success) {
    return res.status(402).json({ error: "Insufficient credits" });
  }

  const { data, error } = await supabase
    .from("phone_numbers")
    .update({ channels: num.channels + 1 })
    .eq("id", req.params.id)
    .eq("account_id", req.accountId!)
    .select()
    .single();

  if (error) return res.status(500).json({ error: error.message });
  res.json(data);
});

// DELETE /api/v1/numbers/:id
router.delete("/:id", async (req: Request, res: Response) => {
  const { error } = await supabase
    .from("phone_numbers")
    .update({ is_active: false })
    .eq("id", req.params.id)
    .eq("account_id", req.accountId!);

  if (error) return res.status(500).json({ error: error.message });
  res.status(204).send();
});

export default router;
