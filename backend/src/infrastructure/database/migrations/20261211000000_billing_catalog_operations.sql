-- Operator-only catalog publication journal. No runtime grants or activation.
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='ceopro_trial_issuer' AND NOT rolcanlogin AND NOT rolsuper
  AND NOT rolbypassrls AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolinherit AND NOT rolreplication)
 OR EXISTS(SELECT FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='ceopro_trial_issuer'))
 OR has_schema_privilege('ceopro_trial_issuer','public','CREATE')
 THEN RAISE EXCEPTION 'Restricted issuer prerequisites required' USING ERRCODE='42501'; END IF;
END $$;
CREATE TABLE public.billing_catalog_operations (
 operation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 binding_id text NOT NULL REFERENCES public.billing_gateway_bindings(binding_id),
 entity_kind text NOT NULL CHECK(entity_kind IN ('product','price')),
 entity_key text NOT NULL CHECK(entity_key<>''),
 price_id uuid REFERENCES public.billing_plan_prices(price_id),
 request jsonb NOT NULL CHECK(jsonb_typeof(request)='object'),
 approved_by uuid NOT NULL REFERENCES public.users(user_id),
 approval_reference text NOT NULL CHECK(btrim(approval_reference)<>''),
 state text NOT NULL DEFAULT 'prepared' CHECK(state IN ('prepared','submitted','succeeded')),
 provider_object_id text CHECK(provider_object_id IS NULL OR btrim(provider_object_id)<>''),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 submitted_at timestamptz,
 completed_at timestamptz,
 UNIQUE(binding_id,entity_kind,entity_key),
 UNIQUE(binding_id,entity_kind,provider_object_id),
 CHECK((entity_kind='price')=(price_id IS NOT NULL)),
 CHECK((state='prepared' AND submitted_at IS NULL AND completed_at IS NULL AND provider_object_id IS NULL)
    OR (state='submitted' AND submitted_at IS NOT NULL AND completed_at IS NULL AND provider_object_id IS NULL)
    OR (state='succeeded' AND completed_at IS NOT NULL AND provider_object_id IS NOT NULL))
);
ALTER TABLE public.billing_catalog_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_catalog_operations FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.billing_catalog_operations FROM PUBLIC,ceopro_app,ceopro_billing_setup,
 ceopro_billing_webhook,ceopro_credit_accounting,ceopro_consent_service,ceopro_billing_observer,
 ceopro_trial_attestor,ceopro_trial_confirmer,ceopro_trial_issuer,ceopro_journey_router;

CREATE FUNCTION public.billing_catalog_operation_guard() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Catalog history is immutable' USING ERRCODE='22023'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.state<>'prepared' THEN RAISE EXCEPTION 'Prepared operation required' USING ERRCODE='22023'; END IF;
  NEW.created_at:=clock_timestamp();
  RETURN NEW;
 END IF;
 IF (NEW.operation_id,NEW.binding_id,NEW.entity_kind,NEW.entity_key,NEW.price_id,NEW.request,
     NEW.approved_by,NEW.approval_reference,NEW.created_at)
 IS DISTINCT FROM (OLD.operation_id,OLD.binding_id,OLD.entity_kind,OLD.entity_key,OLD.price_id,OLD.request,
     OLD.approved_by,OLD.approval_reference,OLD.created_at)
 OR NOT ((OLD.state='prepared' AND NEW.state IN ('submitted','succeeded'))
      OR (OLD.state='submitted' AND NEW.state='succeeded'))
 THEN RAISE EXCEPTION 'Original catalog request and single submission required' USING ERRCODE='22023'; END IF;
 IF NEW.state='submitted' THEN NEW.submitted_at:=clock_timestamp(); END IF;
 IF NEW.state='succeeded' THEN NEW.completed_at:=clock_timestamp(); NEW.submitted_at:=OLD.submitted_at; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.billing_catalog_operation_guard() FROM PUBLIC;
CREATE TRIGGER catalog_operation_history BEFORE INSERT OR UPDATE OR DELETE ON public.billing_catalog_operations
 FOR EACH ROW EXECUTE FUNCTION public.billing_catalog_operation_guard();
