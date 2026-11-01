-- Installation-only reconciliation. No runtime authority or API-lifespan writes.
-- Values already approved in 20261115000000_approved_ai_provider_pricing_v1.sql.
-- Unknown paid paths are visible placeholders, never zero-cost defaults.
CREATE FUNCTION public.billing_catalog_reconcile() RETURNS void
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE
 entry record;
 previous public.provider_cost_schedules%ROWTYPE;
 current_row public.provider_cost_schedules%ROWTYPE;
 subject_key text;
 catalog_version constant text := 'billing-catalog-2026-10-v1';
BEGIN
 LOCK TABLE public.provider_cost_schedules IN SHARE ROW EXCLUSIVE MODE;
 FOR entry IN SELECT * FROM (VALUES
   ('ai','groq','openai/gpt-oss-20b','input_token',0.075::numeric/1000000,
    'https://console.groq.com/docs/model/openai/gpt-oss-20b',DATE '2026-10-28',true),
   ('ai','groq','openai/gpt-oss-20b','output_token',0.30::numeric/1000000,
    'https://console.groq.com/docs/model/openai/gpt-oss-20b',DATE '2026-10-28',true),
   ('data','serpapi','search','request',NULL::numeric,
    'MISSING: runtime provider_billing.py identifies SerpAPI; owner must supply verified account rate',NULL::date,true),
   ('data','gemini_vision','read_image','request',NULL::numeric,
    'MISSING: runtime menu_media.py vision path; owner must supply verified account rate',NULL::date,true)
 ) AS v(budget_kind,provider,operation,unit,price,source,verified_on,cost_is_final)
 LOOP
  subject_key := concat_ws(':',entry.budget_kind,entry.provider,entry.operation,entry.unit);
  SELECT * INTO previous FROM public.provider_cost_schedules
   WHERE budget_kind=entry.budget_kind AND provider=entry.provider
    AND operation=entry.operation AND unit=entry.unit FOR UPDATE;
  -- Preserve ANY existing row, including deliberate NULL/zero/unverified owner values.
  IF FOUND THEN CONTINUE; END IF;
  -- A removed catalog row is a deliberate later decision; don't resurrect it.
  IF EXISTS(SELECT 1 FROM public.entitlement_audit_log WHERE action IN
     ('billing_catalog_bootstrap','provider_pricing_bootstrap','set_price')
     AND subject=subject_key) THEN CONTINUE; END IF;
  IF entry.price IS NOT NULL THEN
   PERFORM public.billing_provider_accounting('set_price',jsonb_build_object(
     'budget_kind',entry.budget_kind,'provider',entry.provider,'operation',entry.operation,'unit',entry.unit,
     'unit_cost_usd',entry.price::text,'source',entry.source,'verified_on',entry.verified_on,
     'approved_by',catalog_version,'reason','Repository-approved AI provider catalog v1; create missing only',
     'safety_margin',NULL,'charged_on_failure',true,'cost_is_final',entry.cost_is_final));
  ELSE
   -- The manual approved-price command intentionally requires an actual price.
   -- A missing-rate inventory entry is not an approved financial value.
   INSERT INTO public.provider_cost_schedules(budget_kind,provider,operation,unit,unit_cost_usd,
      source,configured_by,cost_is_final)
    VALUES(entry.budget_kind,entry.provider,entry.operation,entry.unit,NULL,
      entry.source,catalog_version,entry.cost_is_final);
  END IF;
  SELECT * INTO current_row FROM public.provider_cost_schedules
   WHERE budget_kind=entry.budget_kind AND provider=entry.provider AND operation=entry.operation AND unit=entry.unit;
  INSERT INTO public.entitlement_audit_log(action,subject,new_value,contract_ref,approved_by,reason)
   VALUES('billing_catalog_bootstrap',subject_key,to_jsonb(current_row)||jsonb_build_object(
      'catalog_version',catalog_version,'provenance','catalog/bootstrap','installed_by',session_user),
      catalog_version,catalog_version,'Setup reconciliation: missing canonical entry only; no owner override');
 END LOOP;
END $$;
REVOKE ALL ON FUNCTION public.billing_catalog_reconcile() FROM PUBLIC;
SELECT public.billing_catalog_reconcile();
