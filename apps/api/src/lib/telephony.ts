/**
 * Telephony providers: placing outbound phone calls, plus the signed tokens
 * that let the voice server and our webhooks trust a request.
 *
 * Providers (TELEPHONY_PROVIDER):
 *   mock    no call is placed; for local testing
 *   twilio  Twilio Programmable Voice + Media Streams
 *   exotel  Exotel (Voicebot flow configured in the Exotel dashboard)
 */

import crypto from "crypto";

export type Provider = "mock" | "twilio" | "exotel";

export function provider(): Provider {
  const p = (process.env.TELEPHONY_PROVIDER || "mock").toLowerCase();
  return p === "twilio" || p === "exotel" ? p : "mock";
}

// Same construction as the voice server's calls_db.sign_call
export function signCall(callId: string): string {
  const secret = process.env.WEBHOOK_SECRET || "";
  return crypto.createHmac("sha256", secret).update(callId).digest("hex").slice(0, 32);
}

export function verifyCall(callId: string, token: unknown): boolean {
  if (!process.env.WEBHOOK_SECRET || typeof token !== "string") return false;
  const a = Buffer.from(signCall(callId));
  const b = Buffer.from(token);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

export function apiBase(): string {
  return (process.env.PUBLIC_API_URL || "").replace(/\/$/, "");
}

/** Public voice-server address as ws(s)://, from whatever scheme was configured. */
export function voiceWsBase(): string {
  return (process.env.PUBLIC_VOICE_URL || "")
    .replace(/\/$/, "")
    .replace(/^https:/, "wss:")
    .replace(/^http:/, "ws:");
}

const xmlEscape = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** TwiML that streams a Twilio call's audio to the voice server. */
export function twilioStreamTwiml(callId: string): string {
  return `<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="${xmlEscape(`${voiceWsBase()}/phone/twilio/${callId}`)}">
      <Parameter name="token" value="${signCall(callId)}" />
    </Stream>
  </Connect>
</Response>`;
}

export interface PlacedCall {
  provider: Provider;
  sid: string;
}

/** Ask the provider to ring `to` and connect the call to our voice pipeline. */
export async function placeCall(callId: string, to: string): Promise<PlacedCall> {
  const p = provider();
  if (p === "mock") {
    console.log(`[telephony:mock] would call ${to} for call ${callId}`);
    return { provider: p, sid: `mock-${callId}` };
  }

  if (!apiBase() || !voiceWsBase()) {
    throw new Error("PUBLIC_API_URL and PUBLIC_VOICE_URL must be set to place real calls");
  }
  const t = signCall(callId);
  const statusUrl = `${apiBase()}/api/v1/telephony/status/${callId}?t=${t}`;

  if (p === "twilio") {
    const sid = process.env.TWILIO_ACCOUNT_SID || "";
    const auth = process.env.TWILIO_AUTH_TOKEN || "";
    const from = process.env.TWILIO_FROM_NUMBER || "";
    if (!sid || !auth || !from) throw new Error("Twilio is not configured");

    const form = new URLSearchParams({
      To: to,
      From: from,
      Url: `${apiBase()}/api/v1/telephony/twilio/voice/${callId}?t=${t}`,
      StatusCallback: statusUrl,
      Timeout: "30",
    });
    for (const ev of ["ringing", "answered", "completed"]) form.append("StatusCallbackEvent", ev);

    const res = await fetch(`https://api.twilio.com/2010-04-01/Accounts/${sid}/Calls.json`, {
      method: "POST",
      headers: {
        Authorization: "Basic " + Buffer.from(`${sid}:${auth}`).toString("base64"),
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: form,
    });
    const body: any = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body?.message || `Twilio error ${res.status}`);
    return { provider: p, sid: body.sid };
  }

  // exotel
  const sid = process.env.EXOTEL_ACCOUNT_SID || "";
  const key = process.env.EXOTEL_API_KEY || "";
  const token = process.env.EXOTEL_API_TOKEN || "";
  const callerId = process.env.EXOTEL_CALLER_ID || "";
  const appId = process.env.EXOTEL_APP_ID || "";
  const host = process.env.EXOTEL_SUBDOMAIN || "api.exotel.com";
  if (!sid || !key || !token || !callerId || !appId) throw new Error("Exotel is not configured");

  const form = new URLSearchParams({
    From: to, // Exotel rings this customer number first, then runs the flow
    CallerId: callerId,
    Url: `http://my.exotel.com/${sid}/exoml/start_voice/${appId}`,
    CustomField: callId,
    StatusCallback: statusUrl,
    "StatusCallbackEvents[0]": "terminal",
  });
  const res = await fetch(`https://${host}/v1/Accounts/${sid}/Calls/connect.json`, {
    method: "POST",
    headers: {
      Authorization: "Basic " + Buffer.from(`${key}:${token}`).toString("base64"),
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: form,
  });
  const body: any = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body?.RestException?.Message || `Exotel error ${res.status}`);
  return { provider: p, sid: body?.Call?.Sid || "" };
}

/** Normalise a phone number to E.164, or return null if it can't be one. */
export function normalizePhone(raw: string): string | null {
  const s = raw.replace(/[\s()-]/g, "");
  if (/^[6-9]\d{9}$/.test(s)) return `+91${s}`;
  if (/^0[6-9]\d{9}$/.test(s)) return `+91${s.slice(1)}`;
  if (/^91[6-9]\d{9}$/.test(s)) return `+${s}`;
  if (/^\+[1-9]\d{9,14}$/.test(s)) return s;
  return null;
}

/** Country prefixes we allow calling (abuse guard). Default: India only. */
export function allowedPrefixes(): string[] {
  return (process.env.CALL_ALLOWED_PREFIXES || "+91")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

/**
 * Verify X-Twilio-Signature: base64(HMAC-SHA1(authToken, url + sorted POST params)).
 * Used for webhooks Twilio calls without our per-call token (inbound calls).
 */
export function verifyTwilioSignature(
  signature: unknown,
  path: string,
  params: Record<string, unknown>
): boolean {
  const token = process.env.TWILIO_AUTH_TOKEN || "";
  if (!token || typeof signature !== "string") return false;
  const data =
    apiBase() + path +
    Object.keys(params).sort().map((k) => k + String(params[k])).join("");
  const expected = crypto.createHmac("sha1", token).update(data).digest("base64");
  const a = Buffer.from(expected);
  const b = Buffer.from(signature);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}
