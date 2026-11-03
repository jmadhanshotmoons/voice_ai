-- 008_calls_web_and_provider.sql
-- Dashboard test calls are stored too ("web" direction), and phone calls keep
-- the telephony provider's call id so status callbacks can be matched.

ALTER TABLE public.calls DROP CONSTRAINT IF EXISTS calls_direction_check;
ALTER TABLE public.calls
    ADD CONSTRAINT calls_direction_check CHECK (direction IN ('outbound','inbound','web'));

ALTER TABLE public.calls ADD COLUMN IF NOT EXISTS provider TEXT DEFAULT '';
ALTER TABLE public.calls ADD COLUMN IF NOT EXISTS provider_call_sid TEXT DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_calls_provider_sid ON public.calls(provider_call_sid);
