-- 005_create_leads_billing_numbers.sql

-- Leads captured from calls
CREATE TABLE IF NOT EXISTS public.leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES public.accounts(id),
    employee_id UUID REFERENCES public.employees(id),
    call_id UUID REFERENCES public.calls(id),
    phone_number TEXT,
    name TEXT DEFAULT '',
    captured_data JSONB DEFAULT '{}'::jsonb,
    outcome TEXT DEFAULT '' CHECK (outcome IN ('','interested','not_interested','callback','no_answer','wrong_number')),
    notes TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_leads_account ON public.leads(account_id);
CREATE INDEX idx_leads_outcome ON public.leads(outcome);

-- Phone numbers (rented)
CREATE TABLE IF NOT EXISTS public.phone_numbers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES public.accounts(id),
    number TEXT UNIQUE NOT NULL,
    provider TEXT DEFAULT 'exotel',
    channels INTEGER DEFAULT 1,
    monthly_cost DECIMAL(10,2) DEFAULT 649.00,
    is_active BOOLEAN DEFAULT true,
    assigned_employee_id UUID REFERENCES public.employees(id),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Credit transactions
CREATE TABLE IF NOT EXISTS public.credit_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES public.accounts(id),
    amount DECIMAL(12,2) NOT NULL,  -- positive=topup, negative=usage
    type TEXT NOT NULL CHECK (type IN ('topup','call_usage','number_rental','bonus','refund','ai_action')),
    reference_id UUID,
    description TEXT DEFAULT '',
    balance_after DECIMAL(12,2) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_credit_tx_account ON public.credit_transactions(account_id);
CREATE INDEX idx_credit_tx_created ON public.credit_transactions(created_at DESC);

-- Developer API keys
CREATE TABLE IF NOT EXISTS public.api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES public.accounts(id),
    key_hash TEXT UNIQUE NOT NULL,
    key_prefix TEXT NOT NULL,   -- First 8 chars for display
    name TEXT DEFAULT 'Default',
    is_active BOOLEAN DEFAULT true,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- RLS for all tables
ALTER TABLE public.leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.phone_numbers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.credit_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.api_keys ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own leads" ON public.leads FOR ALL
    USING (account_id IN (SELECT id FROM public.accounts WHERE auth_user_id = auth.uid()));

CREATE POLICY "Users can read own numbers" ON public.phone_numbers FOR ALL
    USING (account_id IN (SELECT id FROM public.accounts WHERE auth_user_id = auth.uid()));

CREATE POLICY "Users can read own transactions" ON public.credit_transactions FOR SELECT
    USING (account_id IN (SELECT id FROM public.accounts WHERE auth_user_id = auth.uid()));

CREATE POLICY "Users can manage own api keys" ON public.api_keys FOR ALL
    USING (account_id IN (SELECT id FROM public.accounts WHERE auth_user_id = auth.uid()));

-- Stored procedure: atomic credit deduction
CREATE OR REPLACE FUNCTION deduct_credits(
    p_account_id UUID,
    p_amount DECIMAL,
    p_type TEXT,
    p_reference_id UUID DEFAULT NULL,
    p_description TEXT DEFAULT ''
) RETURNS JSONB AS $$
DECLARE
    v_balance DECIMAL;
    v_new_balance DECIMAL;
BEGIN
    SELECT credits INTO v_balance FROM public.accounts WHERE id = p_account_id FOR UPDATE;

    IF v_balance IS NULL THEN
        RETURN jsonb_build_object('success', false, 'error', 'Account not found');
    END IF;

    IF v_balance < p_amount THEN
        RETURN jsonb_build_object('success', false, 'error', 'Insufficient credits', 'balance', v_balance);
    END IF;

    v_new_balance := v_balance - p_amount;

    UPDATE public.accounts SET credits = v_new_balance WHERE id = p_account_id;

    INSERT INTO public.credit_transactions (account_id, amount, type, reference_id, description, balance_after)
    VALUES (p_account_id, -p_amount, p_type, p_reference_id, p_description, v_new_balance);

    RETURN jsonb_build_object('success', true, 'balance', v_new_balance, 'deducted', p_amount);
END;
$$ LANGUAGE plpgsql;

-- Stored procedure: add credits
CREATE OR REPLACE FUNCTION add_credits(
    p_account_id UUID,
    p_amount DECIMAL,
    p_type TEXT,
    p_reference_id UUID DEFAULT NULL,
    p_description TEXT DEFAULT ''
) RETURNS JSONB AS $$
DECLARE
    v_new_balance DECIMAL;
BEGIN
    UPDATE public.accounts SET credits = credits + p_amount WHERE id = p_account_id
    RETURNING credits INTO v_new_balance;

    INSERT INTO public.credit_transactions (account_id, amount, type, reference_id, description, balance_after)
    VALUES (p_account_id, p_amount, p_type, p_reference_id, p_description, v_new_balance);

    RETURN jsonb_build_object('success', true, 'balance', v_new_balance, 'added', p_amount);
END;
$$ LANGUAGE plpgsql;
