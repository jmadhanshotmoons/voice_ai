-- 004_create_campaigns.sql

CREATE TABLE IF NOT EXISTS public.campaigns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES public.accounts(id),
    employee_id UUID NOT NULL REFERENCES public.employees(id),
    name TEXT NOT NULL,
    status TEXT DEFAULT 'draft' CHECK (status IN ('draft','active','paused','completed','cancelled')),
    total_contacts INTEGER DEFAULT 0,
    completed_calls INTEGER DEFAULT 0,
    successful_calls INTEGER DEFAULT 0,
    failed_calls INTEGER DEFAULT 0,
    calling_hours JSONB DEFAULT '{"start":"09:00","end":"18:00"}'::jsonb,
    retry_schedule JSONB DEFAULT '[30,120,1440]'::jsonb,
    max_retries INTEGER DEFAULT 3,
    skip_dnd BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.campaign_contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID NOT NULL REFERENCES public.campaigns(id) ON DELETE CASCADE,
    phone_number TEXT NOT NULL,
    name TEXT DEFAULT '',
    custom_fields JSONB DEFAULT '{}'::jsonb,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending','queued','calling','completed','failed','dnd_blocked','skipped')),
    call_id UUID REFERENCES public.calls(id),
    attempts INTEGER DEFAULT 0,
    next_retry_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_campaign_contacts_campaign ON public.campaign_contacts(campaign_id);
CREATE INDEX idx_campaign_contacts_status ON public.campaign_contacts(status);

CREATE TRIGGER campaigns_updated_at
    BEFORE UPDATE ON public.campaigns
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

ALTER TABLE public.campaigns ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.campaign_contacts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can CRUD own campaigns"
    ON public.campaigns FOR ALL
    USING (account_id IN (SELECT id FROM public.accounts WHERE auth_user_id = auth.uid()));

CREATE POLICY "Users can CRUD own campaign contacts"
    ON public.campaign_contacts FOR ALL
    USING (campaign_id IN (
        SELECT id FROM public.campaigns WHERE account_id IN (
            SELECT id FROM public.accounts WHERE auth_user_id = auth.uid()
        )
    ));
