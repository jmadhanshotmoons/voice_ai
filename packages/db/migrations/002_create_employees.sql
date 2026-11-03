-- 002_create_employees.sql
-- AI agents (called "employees") created by each account

CREATE TABLE IF NOT EXISTS public.employees (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES public.accounts(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    language TEXT DEFAULT 'hi-IN',
    voice_provider TEXT DEFAULT 'cartesia' CHECK (voice_provider IN ('cartesia','sarvam')),
    voice_id TEXT DEFAULT '',
    voice_tier TEXT DEFAULT 'standard' CHECK (voice_tier IN ('standard','premium')),
    greeting TEXT DEFAULT 'Namaste! Main aapki kaise madad kar sakti hoon?',
    system_prompt TEXT DEFAULT '',
    knowledge_base TEXT DEFAULT '',
    capture_fields TEXT[] DEFAULT ARRAY['name','interest'],
    mode TEXT DEFAULT 'instant' CHECK (mode IN ('instant','bulk','inbound')),
    tools_enabled TEXT[] DEFAULT ARRAY['capture_field'],
    max_call_duration_s INTEGER DEFAULT 300,
    is_active BOOLEAN DEFAULT true,
    is_published BOOLEAN DEFAULT false,
    slug TEXT UNIQUE,
    webhook_url TEXT DEFAULT '',
    webhook_secret TEXT DEFAULT encode(gen_random_bytes(32), 'hex'),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_employees_account ON public.employees(account_id);
CREATE INDEX idx_employees_slug ON public.employees(slug);

CREATE TRIGGER employees_updated_at
    BEFORE UPDATE ON public.employees
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

ALTER TABLE public.employees ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can CRUD own employees"
    ON public.employees FOR ALL
    USING (account_id IN (SELECT id FROM public.accounts WHERE auth_user_id = auth.uid()));
