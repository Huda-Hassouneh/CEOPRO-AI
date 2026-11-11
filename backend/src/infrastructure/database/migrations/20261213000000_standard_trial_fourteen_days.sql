-- Owner decision 2026-11-09: all three canonical Standard tiers offer 14 days.
-- Future offers only. Do not modify historical subscriptions, local trials,
-- frozen reservations, provider objects, financial terms or current entitlements.
-- Use the same serialization boundary as Platform Owner catalog operations.
DO $$
DECLARE p record;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_platform_authority',0));
 FOR p IN SELECT plan_key,trial_days FROM public.usage_plans
   WHERE plan_key IN ('starter','growth','enterprise') AND trial_days<>14
   ORDER BY plan_key FOR UPDATE
 LOOP
  UPDATE public.usage_plans SET trial_days=14 WHERE plan_key=p.plan_key;
  INSERT INTO public.keel_platform_audit(actor_role,action,subject,old_value,new_value,reason,outcome)
   VALUES('installer','standard_trial_policy_update','plan:'||p.plan_key,
    jsonb_build_object('trial_days',p.trial_days),jsonb_build_object('trial_days',14),
    'Owner-approved 2026-11-09: 14-day future Standard plan trials; historical rights unchanged','succeeded');
 END LOOP;
END $$;
