-- Forward only: preserve completed companies, trials, contracts and existing RLS.
ALTER TABLE public.companies ADD COLUMN onboarding_profile jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.companies ADD CONSTRAINT companies_onboarding_profile_object CHECK (jsonb_typeof(onboarding_profile) = 'object');
COMMENT ON COLUMN public.companies.onboarding_profile IS 'Tenant-scoped original onboarding choices and optimistic revision; never billing or entitlement authority.';
