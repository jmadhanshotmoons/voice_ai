/**
 * Shared TypeScript types used across API and frontend.
 */

export interface Account {
  id: string;
  auth_user_id: string;
  email: string;
  company_name: string;
  plan: "trial" | "starter" | "growth" | "enterprise";
  credits: number;
  is_admin: boolean;
  developer_mode: boolean;
  created_at: string;
}

export interface Employee {
  id: string;
  account_id: string;
  name: string;
  language: string;
  voice_provider: "cartesia" | "sarvam";
  voice_id: string;
  voice_tier: "standard" | "premium";
  greeting: string;
  system_prompt: string;
  knowledge_base: string;
  capture_fields: string[];
  mode: "instant" | "bulk" | "inbound";
  tools_enabled: string[];
  max_call_duration_s: number;
  is_active: boolean;
  slug: string | null;
  webhook_url: string;
  webhook_secret: string;
  created_at: string;
}

export interface Call {
  id: string;
  account_id: string;
  employee_id: string;
  phone_number: string;
  direction: "outbound" | "inbound";
  status: "pending" | "ringing" | "connected" | "completed" | "failed" | "no_answer";
  duration_seconds: number;
  credits_used: number;
  transcript: TranscriptEntry[];
  summary: string;
  sentiment: string;
  captured_fields: Record<string, string>;
  recording_url: string;
  created_at: string;
}

export interface TranscriptEntry {
  role: "user" | "assistant";
  text: string;
  ts: number;
}

export interface Lead {
  id: string;
  account_id: string;
  employee_id: string;
  call_id: string;
  phone_number: string;
  name: string;
  captured_data: Record<string, string>;
  outcome: string;
  created_at: string;
}

export interface CreditTransaction {
  id: string;
  account_id: string;
  amount: number;
  type: "topup" | "call_usage" | "number_rental" | "bonus" | "refund";
  reference_id: string | null;
  description: string;
  balance_after: number;
  created_at: string;
}

// Billing rates in INR
export const RATES = {
  standard_per_min: 5,
  premium_per_min: 6.8,
  ai_per_use: 0.2,
  number_monthly: 649,
  sandbox_per_msg: 0.2,
  gst_pct: 18,
} as const;

// Small first top-up so anyone can start; bonus credits grow with the pack. Keep in sync with the billing page.
export const CREDIT_PACKS = [
  { amount: 499, bonus: 0, label: "Trial" },
  { amount: 999, bonus: 50, label: "Starter" },
  { amount: 2499, bonus: 150, label: "Basic" },
  { amount: 9999, bonus: 800, label: "Growth" },
  { amount: 24999, bonus: 2500, label: "Scale" },
  { amount: 50000, bonus: 6000, label: "Pro" },
] as const;
