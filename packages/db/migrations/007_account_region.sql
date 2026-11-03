-- 007_account_region.sql
-- Store the region picked at signup; the web app uses it to default the language.

ALTER TABLE public.accounts ADD COLUMN IF NOT EXISTS region TEXT DEFAULT '';

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.accounts (auth_user_id, email, region)
    VALUES (NEW.id, NEW.email, COALESCE(NEW.raw_user_meta_data->>'region', ''))
    ON CONFLICT (auth_user_id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;
