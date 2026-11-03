/**
 * Billing routes -- credit balance, top-up, transactions, Razorpay.
 *
 * SECURITY:
 * - Razorpay signature verification on payment callback (prevents forged payments)
 * - Credit operations use DB stored procedure with FOR UPDATE lock (prevents race conditions)
 * - Amount validated server-side against CREDIT_PACKS (prevents price tampering)
 */

import { Router, Request, Response } from "express";
import { z } from "zod";
import crypto from "crypto";
import { createClient } from "@supabase/supabase-js";
import { validate } from "../middleware/validate";
import { CREDIT_PACKS, RATES } from "../types";

const router = Router();
const supabase = createClient(
  process.env.SUPABASE_URL || "",
  process.env.SUPABASE_SERVICE_KEY || ""
);

// GET /api/v1/billing -- current balance + rates
router.get("/", async (req: Request, res: Response) => {
  const { data: account } = await supabase
    .from("accounts")
    .select("credits, plan")
    .eq("id", req.accountId!)
    .single();

  if (!account) return res.status(404).json({ error: "Account not found" });

  res.json({
    credits: account.credits,
    plan: account.plan,
    rates: RATES,
    packs: CREDIT_PACKS,
  });
});

// GET /api/v1/billing/transactions -- transaction history
router.get("/transactions", async (req: Request, res: Response) => {
  const limit = Math.min(100, parseInt(req.query.limit as string) || 50);
  const offset = parseInt(req.query.offset as string) || 0;

  const { data, error } = await supabase
    .from("credit_transactions")
    .select("*")
    .eq("account_id", req.accountId!)
    .order("created_at", { ascending: false })
    .range(offset, offset + limit - 1);

  if (error) return res.status(500).json({ error: error.message });
  res.json({ transactions: data });
});

// POST /api/v1/billing/create-order -- create Razorpay order
const createOrderSchema = z.object({
  pack_index: z.number().int().min(0).max(CREDIT_PACKS.length - 1),
});

router.post("/create-order", validate(createOrderSchema), async (req: Request, res: Response) => {
  const Razorpay = require("razorpay");
  const rzp = new Razorpay({
    key_id: process.env.RAZORPAY_KEY_ID,
    key_secret: process.env.RAZORPAY_KEY_SECRET,
  });

  const pack = CREDIT_PACKS[req.body.pack_index];
  // SECURITY: Amount comes from server-side CREDIT_PACKS, NEVER from client
  const amountWithGst = Math.round(pack.amount * (1 + RATES.gst_pct / 100) * 100); // paise

  try {
    const order = await rzp.orders.create({
      amount: amountWithGst,
      currency: "INR",
      notes: {
        account_id: req.accountId!,
        pack_index: req.body.pack_index,
        credits: pack.amount + pack.bonus,
      },
    });

    res.json({
      order_id: order.id,
      amount: amountWithGst,
      currency: "INR",
      key_id: process.env.RAZORPAY_KEY_ID,
    });
  } catch (err: any) {
    res.status(500).json({ error: "Failed to create payment order" });
  }
});

// POST /api/v1/billing/verify-payment -- verify Razorpay signature + add credits
const verifyPaymentSchema = z.object({
  razorpay_order_id: z.string(),
  razorpay_payment_id: z.string(),
  razorpay_signature: z.string(),
});

router.post("/verify-payment", validate(verifyPaymentSchema), async (req: Request, res: Response) => {
  const { razorpay_order_id, razorpay_payment_id, razorpay_signature } = req.body;

  // SECURITY: Verify HMAC-SHA256 signature to prevent forged payment callbacks
  const expectedSignature = crypto
    .createHmac("sha256", process.env.RAZORPAY_KEY_SECRET || "")
    .update(`${razorpay_order_id}|${razorpay_payment_id}`)
    .digest("hex");

  // Timing-safe comparison to prevent timing attacks
  if (!crypto.timingSafeEqual(
    Buffer.from(razorpay_signature),
    Buffer.from(expectedSignature)
  )) {
    return res.status(400).json({ error: "Invalid payment signature" });
  }

  // Fetch order to get credits amount from server-side notes
  const Razorpay = require("razorpay");
  const rzp = new Razorpay({
    key_id: process.env.RAZORPAY_KEY_ID,
    key_secret: process.env.RAZORPAY_KEY_SECRET,
  });

  const order = await rzp.orders.fetch(razorpay_order_id);
  const credits = parseInt(order.notes.credits);

  if (!credits || order.notes.account_id !== req.accountId) {
    return res.status(400).json({ error: "Order mismatch" });
  }

  // Add credits using atomic stored procedure
  const { data, error } = await supabase.rpc("add_credits", {
    p_account_id: req.accountId!,
    p_amount: credits,
    p_type: "topup",
    p_reference_id: razorpay_payment_id,
    p_description: `Razorpay payment ${razorpay_payment_id}`,
  });

  if (error) return res.status(500).json({ error: "Failed to add credits" });
  res.json({ success: true, credits_added: credits, new_balance: data?.balance });
});

export default router;
