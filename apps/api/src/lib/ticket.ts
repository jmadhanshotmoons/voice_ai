/**
 * Short-lived, signed tickets for browser WebSocket calls.
 *
 * Browsers cannot set an Authorization header on a WebSocket, so the dashboard asks the API
 * (authenticated) for a ticket and passes it on the connection URL. A ticket is bound to one
 * subject (the employee being tested) and expires after TTL seconds, so a leaked URL is useless.
 * The voice server verifies it with the same construction (utils/calls_db.valid_ticket).
 */

import crypto from "crypto";

export const TICKET_TTL_S = 60;

function mac(subject: string, exp: number): string {
  const secret = process.env.WEBHOOK_SECRET || "";
  return crypto.createHmac("sha256", secret).update(`ticket:${subject}:${exp}`).digest("hex");
}

export function signTicket(subject: string): string {
  const exp = Math.floor(Date.now() / 1000) + TICKET_TTL_S;
  return `${exp}.${mac(subject, exp)}`;
}
