-- Only verified activation materializes purchased premium modules.
-- Core rights, numeric terms and existing RLS/grants are unchanged.
CREATE FUNCTION public.keel_paid_custom_catalog_snapshot(p_tenant uuid,p_base jsonb)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE selected jsonb; effective jsonb; revision uuid;
BEGIN
 SELECT coalesce(r.configuration->'enabledFeatures','[]'::jsonb),x.revision_id INTO selected,revision
 FROM public.billing_custom_contract_activations x
 JOIN public.billing_custom_quote_revisions r ON (r.tenant_id,r.quote_id,r.revision_id)=(x.tenant_id,x.quote_id,x.revision_id)
 JOIN public.tenant_custom_contracts c ON c.tenant_id=x.tenant_id AND c.contract_ref='custom-quote:'||x.quote_id::text||':'||x.revision_id::text
 JOIN public.billing_subscriptions s ON s.tenant_id=x.tenant_id AND s.stripe_subscription_id=x.stripe_subscription_id
 WHERE x.tenant_id=p_tenant AND s.plan_key='custom' AND s.status='active'
 ORDER BY x.activated_at DESC LIMIT 1;
 SELECT coalesce(jsonb_agg(code ORDER BY code),'[]'::jsonb) INTO effective FROM (
   SELECT jsonb_array_elements_text(coalesce(p_base->'entitlements','[]'::jsonb)) AS code
   EXCEPT SELECT unnest(ARRAY['market_intelligence','demand_prediction','competitor_management'])
   UNION SELECT value FROM jsonb_array_elements_text(coalesce(selected,'[]'::jsonb)) AS chosen(value)
    WHERE value=ANY(ARRAY['market_intelligence','demand_prediction','competitor_management'])
 ) rights;
 RETURN jsonb_set(jsonb_set(p_base,'{entitlements}',effective),'{paid_custom_quote_revision}',coalesce(to_jsonb(revision),'null'::jsonb));
END $$;
REVOKE ALL ON FUNCTION public.keel_paid_custom_catalog_snapshot(uuid,jsonb) FROM PUBLIC,ceopro_app;
CREATE OR REPLACE FUNCTION public.keel_capture_plan_catalog_snapshot()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.plan_key = OLD.plan_key THEN
        IF OLD.catalog_snapshot IS NOT NULL THEN
            NEW.catalog_snapshot := OLD.catalog_snapshot;
            IF NEW.plan_key='custom' AND NEW.source='stripe' THEN
                NEW.catalog_snapshot := public.keel_paid_custom_catalog_snapshot(NEW.tenant_id,NEW.catalog_snapshot);
            END IF;
            RETURN NEW;
        END IF;
    END IF;

    SELECT jsonb_build_object(
        'catalog_version', (SELECT version FROM public.entitlement_catalog_version WHERE singleton IS TRUE),
        'plan_key', p.plan_key,
        'display_name', p.display_name,
        'features', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'feature_code', f.feature_code, 'unit', f.unit,
                'aggregation_type', f.aggregation_type, 'reset_cycle', f.reset_cycle,
                'limit_value', l.limit_value, 'trial_limit_value', l.trial_limit_value
            ) ORDER BY f.feature_code)
            FROM public.usage_plan_limits l
            JOIN public.usage_features f ON f.feature_code = l.feature_code
            WHERE l.plan_key = p.plan_key
        ), '[]'::jsonb),
        'entitlements', COALESCE((
            SELECT jsonb_agg(e.feature_code ORDER BY e.feature_code)
            FROM public.usage_plan_entitlements e WHERE e.plan_key = p.plan_key
        ), '[]'::jsonb)
    ) INTO NEW.catalog_snapshot
    FROM public.usage_plans p WHERE p.plan_key = NEW.plan_key;

    IF NEW.catalog_snapshot IS NULL THEN
        RAISE EXCEPTION 'plan catalog snapshot unavailable for plan %', NEW.plan_key;
    END IF;
    IF NEW.plan_key='custom' AND NEW.source='stripe' THEN
        NEW.catalog_snapshot := public.keel_paid_custom_catalog_snapshot(NEW.tenant_id,NEW.catalog_snapshot);
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.keel_capture_plan_catalog_snapshot() FROM PUBLIC,ceopro_app;
CREATE FUNCTION public.keel_materialize_paid_custom_modules()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public,pg_temp AS $$
BEGIN
 UPDATE public.tenant_plan_assignments a SET catalog_snapshot=a.catalog_snapshot
 WHERE a.tenant_id=NEW.tenant_id AND a.plan_key='custom' AND a.source='stripe'
   AND EXISTS(SELECT 1 FROM public.billing_subscriptions s WHERE s.tenant_id=NEW.tenant_id
       AND s.stripe_subscription_id=NEW.stripe_subscription_id AND s.status='active');
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.keel_materialize_paid_custom_modules() FROM PUBLIC,ceopro_app;
CREATE TRIGGER paid_custom_modules_snapshot AFTER INSERT ON public.billing_custom_contract_activations
FOR EACH ROW EXECUTE FUNCTION public.keel_materialize_paid_custom_modules();
-- Narrow repair of currently active, verified Stripe Custom contracts only.
UPDATE public.tenant_plan_assignments a SET catalog_snapshot=a.catalog_snapshot
WHERE a.plan_key='custom' AND a.source='stripe' AND a.status='active'
 AND EXISTS(SELECT 1 FROM public.billing_custom_contract_activations x
   JOIN public.billing_subscriptions s ON s.tenant_id=x.tenant_id AND s.stripe_subscription_id=x.stripe_subscription_id
   JOIN public.tenant_custom_contracts c ON c.tenant_id=x.tenant_id AND c.contract_ref='custom-quote:'||x.quote_id::text||':'||x.revision_id::text
   WHERE x.tenant_id=a.tenant_id AND s.status='active');
DROP FUNCTION public.billing_custom_paid_modules(uuid);
