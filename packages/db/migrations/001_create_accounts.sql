-- 001_create_accounts.sql
-- Core accounts table (tenants/customers of the platform)

CREATE TABLE IF NOT EXISTS public.accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_user_id UUID UNIQUE NOT NULL,  -- Links to Supabase auth.users
    email TEXT UNIQUE NOT NULL,
    company_name TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    plan TEXT DEFAULT 'trial' CHECK (plan IN ('trial','starter','growth','enterprise')),
    credits DECIMAL(12,2) DEFAULT 50.00,
    is_admin BOOLEAN DEFAULT false,
    developer_mode BOOLEAN DEFAULT false,
    onboarded BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accounts_updated_at
    BEFORE UPDATE ON public.accounts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- RLS
ALTER TABLE public.accounts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own account"
    ON public.accounts FOR SELECT
    USING (auth.uid() = auth_user_id);

CREATE POLICY "Users can update own account"
    ON public.accounts FOR UPDATE
    USING (auth.uid() = auth_user_id);
