-- 003_create_calls.sql
-- Every call made or received

CREATE TABLE IF NOT EXISTS public.calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES public.accounts(id),
    employee_id UUID REFERENCES public.employees(id),
    phone_number TEXT NOT NULL,
    direction TEXT DEFAULT 'outbound' CHECK (direction IN ('outbound','inbound')),
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending','ringing','connected','completed','failed','no_answer')),
    duration_seconds INTEGER DEFAULT 0,
    credits_used DECIMAL(10,2) DEFAULT 0,
    transcript JSONB DEFAULT '[]'::jsonb,
    summary TEXT DEFAULT '',
    sentiment TEXT DEFAULT '',
    captured_fields JSONB DEFAULT '{}'::jsonb,
    recording_url TEXT DEFAULT '',
    campaign_id UUID,
    lead_id UUID,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_calls_account ON public.calls(account_id);
CREATE INDEX idx_calls_employee ON public.calls(employee_id);
CREATE INDEX idx_calls_status ON public.calls(status);
CREATE INDEX idx_calls_created ON public.calls(created_at DESC);

ALTER TABLE public.calls ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own calls"
    ON public.calls FOR SELECT
    USING (account_id IN (SELECT id FROM public.accounts WHERE auth_user_id = auth.uid()));
