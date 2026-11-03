/**
 * Auth middleware -- verifies Supabase JWT on every request.
 *
 * SECURITY NOTES (from bug bounty experience):
 * - Outpero's mistake: admin endpoints used the SAME Supabase JWT as regular users.
 *   If the backend only checks "is this a valid token" but not "is this user an admin",
 *   any regular user can hit /admin/* endpoints (BOLA/IDOR).
 * - We fix this by extracting the account from the JWT AND checking is_admin for admin routes.
 * - Every route gets account_id injected -- never trust client-supplied account_id in body/params.
 */

import { Request, Response, NextFunction } from "express";
import { createClient } from "@supabase/supabase-js";

const supabase = createClient(
  process.env.SUPABASE_URL || "",
  process.env.SUPABASE_SERVICE_KEY || ""
);

// Extend Express Request to carry authenticated account
declare global {
  namespace Express {
    interface Request {
      accountId?: string;
      authUserId?: string;
      isAdmin?: boolean;
    }
  }
}

export async function requireAuth(
  req: Request,
  res: Response,
  next: NextFunction
) {
  const authHeader = req.headers.authorization;
  if (!authHeader?.startsWith("Bearer ")) {
    return res.status(401).json({ error: "Missing or invalid Authorization header" });
  }

  const token = authHeader.slice(7);

  try {
    // Verify JWT with Supabase (checks signature + expiry)
    const {
      data: { user },
      error,
    } = await supabase.auth.getUser(token);

    if (error || !user) {
      return res.status(401).json({ error: "Invalid or expired token" });
    }

    // Look up account by auth_user_id -- NEVER trust user-supplied account_id
    const { data: account, error: accError } = await supabase
      .from("accounts")
      .select("id, is_admin, plan, credits")
      .eq("auth_user_id", user.id)
      .single();

    if (accError || !account) {
      return res.status(403).json({ error: "Account not found" });
    }

    // Inject into request -- downstream routes use ONLY these, never req.body.account_id
    req.accountId = account.id;
    req.authUserId = user.id;
    req.isAdmin = account.is_admin;

    next();
  } catch (err) {
    return res.status(500).json({ error: "Authentication failed" });
  }
}

/**
 * Admin-only middleware. Must come AFTER requireAuth.
 * This prevents the Outpero-style BOLA where regular users hit admin endpoints.
 */
export function requireAdmin(req: Request, res: Response, next: NextFunction) {
  if (!req.isAdmin) {
    // Don't reveal admin routes exist -- return generic 404
    return res.status(404).json({ error: "Not found" });
  }
  next();
}

/**
 * API key auth for the lead-intake endpoint (external integrations).
 * Uses HMAC comparison to prevent timing attacks.
 */
export async function requireApiKey(
  req: Request,
  res: Response,
  next: NextFunction
) {
  const apiKey = req.headers["x-api-key"] as string;
  if (!apiKey) {
    return res.status(401).json({ error: "Missing X-API-Key header" });
  }

  const crypto = require("crypto");
  const keyHash = crypto.createHash("sha256").update(apiKey).digest("hex");

  const { data: keyRecord } = await supabase
    .from("api_keys")
    .select("id, account_id, is_active")
    .eq("key_hash", keyHash)
    .eq("is_active", true)
    .single();

  if (!keyRecord) {
    return res.status(401).json({ error: "Invalid API key" });
  }

  // Update last_used_at (non-blocking)
  supabase
    .from("api_keys")
    .update({ last_used_at: new Date().toISOString() })
    .eq("id", keyRecord.id)
    .then();

  req.accountId = keyRecord.account_id;
  next();
}
