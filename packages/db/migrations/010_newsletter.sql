-- Newsletter sign-ups from the website footer.
-- Written only by the API (service role). RLS is on with no policies, so the browser keys can never read or write it.

CREATE TABLE IF NOT EXISTS public.newsletter_subscribers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,  -- the API stores it lower-cased
    created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE public.newsletter_subscribers ENABLE ROW LEVEL SECURITY;
