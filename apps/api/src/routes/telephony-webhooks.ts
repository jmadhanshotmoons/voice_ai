/**
 * Telephony webhook routes -- the phone provider calls these during/after a call.
 *
 * SECURITY:
 * - Every callback URL we hand a provider carries ?t=<HMAC of the call id>;
 *   requests without a valid token are rejected (no forging status updates).
 * - Status updates are idempotent and never downgrade a finished call.
 * - Credits are billed once: the voice server bills real calls when they end;
 *   this route only bills a call the voice server never saw.
 */

import { RATES } from "../types";
import { Router, Request, Response, NextFunction } from "express";
import { createClient } from "@supabase/supabase-js";
import { verifyCall, twilioStreamTwiml, verifyTwilioSignature } from "../lib/telephony";

const router = Router();
const supabase = createClient(
  process.env.SUPABASE_URL || "",
  process.env.SUPABASE_SERVICE_KEY || ""
);

function requireCallToken(req: Request, res: Response, next: NextFunction) {
  if (!verifyCall(req.params.callId, req.query.t)) {
    return res.status(403).json({ error: "Forbidden" });
  }
  next();
}

const xml = (res: Response, body: string) => {
  res.set("Content-Type", "text/xml");
  res.send(body);
};
const say = (text: string) =>
  `<?xml version="1.0" encoding="UTF-8"?><Response><Say>${text}</Say><Hangup/></Response>`;

/**
 * POST /api/v1/telephony/twilio/voice/:callId
 * Twilio asks what to do when the person answers: stream the audio to us.
 */
router.post("/twilio/voice/:callId", requireCallToken, async (req: Request, res: Response) => {
  const { data: call } = await supabase.from("calls").select("id").eq("id", req.params.callId).single();
  if (!call) return xml(res, say("Sorry, this call is no longer available."));
  xml(res, twilioStreamTwiml(call.id));
});

/**
 * POST /api/v1/telephony/twilio/inbound
 * A caller dialled our Twilio number. Find the employee assigned to it.
 */
router.post("/twilio/inbound", async (req: Request, res: Response) => {
  if (!verifyTwilioSignature(req.headers["x-twilio-signature"], req.originalUrl, req.body)) {
    return res.status(403).send("Forbidden");
  }
  const to = req.body.To as string;
  const from = req.body.From as string;

  const { data: phoneNumber } = await supabase
    .from("phone_numbers")
    .select("account_id, assigned_employee_id")
    .eq("number", to)
    .eq("is_active", true)
    .single();

  if (!phoneNumber?.assigned_employee_id) {
    return xml(res, say("Sorry, this number is not configured."));
  }

  const { data: call } = await supabase
    .from("calls")
    .insert({
      account_id: phoneNumber.account_id,
      employee_id: phoneNumber.assigned_employee_id,
      phone_number: from,
      direction: "inbound",
      status: "ringing",
      provider: "twilio",
      provider_call_sid: req.body.CallSid || "",
    })
    .select("id")
    .single();
  if (!call) return xml(res, say("Please try again later."));

  xml(res, twilioStreamTwiml(call.id));
});

/**
 * POST /api/v1/telephony/status/:callId
 * Provider status callbacks (Twilio and Exotel field names are both accepted).
 */
router.post("/status/:callId", requireCallToken, async (req: Request, res: Response) => {
  const { callId } = req.params;
  const raw = String(req.body.CallStatus || req.body.Status || req.query.Status || "").toLowerCase();
  const duration = parseInt(req.body.CallDuration || req.body.Duration || req.query.Duration || "0") || 0;
  const recordingUrl = req.body.RecordingUrl || req.query.RecordingUrl || "";

  const terminal: Record<string, string> = {
    completed: "completed",
    "no-answer": "no_answer",
    busy: "no_answer",
    failed: "failed",
    canceled: "failed",
  };

  const { data: call } = await supabase
    .from("calls")
    .select("id, account_id, employee_id, status, credits_used, duration_seconds")
    .eq("id", callId)
    .single();
  if (!call) return res.status(404).json({ error: "Call not found" });

  const ourStatus = terminal[raw];

  // Non-final updates: only note that it is ringing
  if (!ourStatus) {
    if (raw === "ringing" && call.status === "pending") {
      await supabase.from("calls").update({ status: "ringing" }).eq("id", callId);
    }
    return res.json({ ok: true });
  }

  const finishedByVoiceServer = call.status === "completed" && Number(call.credits_used) > 0;
  const update: Record<string, unknown> = { ended_at: new Date().toISOString() };
  // A call the voice server is still wrapping up (summary, billing) stays "connected";
  // the voice server marks it completed when its record is fully saved.
  const voiceServerOwnsStatus = call.status === "connected" && ourStatus === "completed";
  if (call.status !== "completed" && !voiceServerOwnsStatus) update.status = ourStatus;
  if (!call.duration_seconds && duration) update.duration_seconds = duration;
  if (recordingUrl) update.recording_url = recordingUrl;
  await supabase.from("calls").update(update).eq("id", callId);

  // Bill only if the voice server did not (e.g. it never received the audio stream)
  if (ourStatus === "completed" && duration > 0 && !finishedByVoiceServer && !Number(call.credits_used)) {
    const { data: employee } = await supabase
      .from("employees")
      .select("voice_tier")
      .eq("id", call.employee_id)
      .single();

    const rate = employee?.voice_tier === "premium" ? RATES.premium_per_min : RATES.standard_per_min;
    const credits = Math.round(Math.max(1, Math.ceil(duration / 30)) * 0.5 * rate * 100) / 100;

    await supabase.rpc("deduct_credits", {
      p_account_id: call.account_id,
      p_amount: credits,
      p_type: "call_usage",
      p_reference_id: callId,
      p_description: `Call ${duration}s at Rs ${rate}/min`,
    });
    await supabase.from("calls").update({ credits_used: credits }).eq("id", callId);
  }

  res.json({ ok: true });
});

export default router;
