-- Right to delete + data retention.
-- Most child tables reference accounts without ON DELETE CASCADE, so deletion is done in order here.
-- Called only by the API (service role) after the user re-authenticates.

CREATE OR REPLACE FUNCTION public.delete_account_data(p_account_id UUID)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    DELETE FROM public.campaign_contacts
        WHERE campaign_id IN (SELECT id FROM public.campaigns WHERE account_id = p_account_id);
    DELETE FROM public.leads WHERE account_id = p_account_id;
    DELETE FROM public.credit_transactions WHERE account_id = p_account_id;
    DELETE FROM public.api_keys WHERE account_id = p_account_id;
    DELETE FROM public.phone_numbers WHERE account_id = p_account_id;
    DELETE FROM public.campaigns WHERE account_id = p_account_id;
    DELETE FROM public.calls WHERE account_id = p_account_id;
    DELETE FROM public.employees WHERE account_id = p_account_id;
    DELETE FROM public.accounts WHERE id = p_account_id;
END;
$$;

-- Retention: call transcripts and recordings older than p_days are wiped; billing rows are kept for accounting.
CREATE OR REPLACE FUNCTION public.purge_old_call_content(p_days INTEGER DEFAULT 180)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    n INTEGER;
BEGIN
    UPDATE public.calls
       SET transcript = '[]'::jsonb, summary = ''
     WHERE created_at < now() - make_interval(days => p_days)
       AND (transcript IS DISTINCT FROM '[]'::jsonb OR COALESCE(summary, '') <> '');
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END;
$$;

-- Only the service role may run these
REVOKE ALL ON FUNCTION public.delete_account_data(UUID) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.purge_old_call_content(INTEGER) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.delete_account_data(UUID) TO service_role;
GRANT EXECUTE ON FUNCTION public.purge_old_call_content(INTEGER) TO service_role;
