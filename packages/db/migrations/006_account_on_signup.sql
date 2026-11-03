-- 006_account_on_signup.sql
-- Create an accounts row automatically when a user signs up via Supabase Auth.

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.accounts (auth_user_id, email)
    VALUES (NEW.id, NEW.email)
    ON CONFLICT (auth_user_id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- Backfill users created before this trigger existed
INSERT INTO public.accounts (auth_user_id, email)
SELECT id, email FROM auth.users
ON CONFLICT (auth_user_id) DO NOTHING;
