/**
 * Newsletter sign-up for the website footer (public, no login).
 *
 * SECURITY: strict rate limit per IP, validated email, a honeypot field for bots, and the same
 * response whether or not the address was already subscribed (no way to probe who is on the list).
 */

import { Router, Request, Response } from "express";
import { createClient } from "@supabase/supabase-js";
import { z } from "zod";
import rateLimit from "express-rate-limit";
import { validate } from "../middleware/validate";
import { log } from "../lib/log";

const router = Router();
const supabase = createClient(process.env.SUPABASE_URL || "", process.env.SUPABASE_SERVICE_KEY || "");

const limiter = rateLimit({
  windowMs: 60 * 60 * 1000,
  max: 5,
  standardHeaders: true,
  legacyHeaders: false,
  message: { error: "Too many attempts. Try again later." },
});

const schema = z.object({
  email: z.string().trim().toLowerCase().email().max(254),
  website: z.string().max(0).optional(), // honeypot: real people never fill this in
});

// POST /api/v1/newsletter
router.post("/", limiter, validate(schema), async (req: Request, res: Response) => {
  const { error } = await supabase
    .from("newsletter_subscribers")
    .upsert({ email: req.body.email }, { onConflict: "email", ignoreDuplicates: true });
  // Unique index is on lower(email), so a duplicate surfaces as a conflict error: treat it as success
  if (error && !/duplicate|unique|conflict/i.test(error.message)) {
    log.error("newsletter_failed", { error: error.message });
    return res.status(500).json({ error: "Something went wrong" });
  }
  res.status(201).json({ subscribed: true });
});

export default router;
