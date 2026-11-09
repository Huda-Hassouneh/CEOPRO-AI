-- Dormant only: no mappings/backfills, provider calls, bindings or rights are created.
ALTER TABLE public.billing_customer_references ADD CONSTRAINT customer_reference_result_identity
 UNIQUE(reference_id,tenant_id,binding_id,provider_customer_id);
CREATE TABLE public.billing_customer_operations (
 operation_id uuid PRIMARY KEY,
 tenant_id uuid NOT NULL REFERENCES public.companies(tenant_id),
 binding_id text NOT NULL REFERENCES public.billing_gateway_bindings(binding_id),
 initiated_by uuid NOT NULL REFERENCES public.users(user_id),
 request_identity text NOT NULL CHECK(length(request_identity) BETWEEN 1 AND 255),
 idempotency_key text NOT NULL CHECK(idempotency_key='keel-customer-'||operation_id::text),
 logical_request text NOT NULL CHECK(jsonb_typeof(logical_request::jsonb)='object'),
 transport_request text NOT NULL CHECK(jsonb_typeof(transport_request::jsonb)='object'),
 encoder_version text NOT NULL CHECK(encoder_version<>''),
 api_version text NOT NULL CHECK(api_version<>''),
 replay_supported boolean NOT NULL,
 replay_window_seconds integer NOT NULL CHECK(replay_window_seconds>=0),
 dispatch_timeout_seconds integer NOT NULL CHECK(dispatch_timeout_seconds BETWEEN 1 AND 20),
 state text NOT NULL DEFAULT 'prepared' CHECK(state IN
  ('prepared','submitted','unknown','reconciliation_required','succeeded','rejected','cancelled')),
 version bigint NOT NULL DEFAULT 0 CHECK(version>=0),
 claim_token uuid,
 claim_until timestamptz,
 first_submitted_at timestamptz,
 replay_deadline timestamptz,
 dispatch_count integer NOT NULL DEFAULT 0 CHECK(dispatch_count>=0),
 reference_id uuid,
 provider_customer_id text,
 confirmation jsonb,
 last_error text CHECK(last_error IN
  ('rejected','unavailable','outcome_unknown','not_found','unsupported_capability',
   'replay_expired','inconclusive','conflict','non_creation')),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(binding_id,idempotency_key),
 UNIQUE(tenant_id,binding_id,request_identity),
 FOREIGN KEY(reference_id,tenant_id,binding_id,provider_customer_id)
  REFERENCES public.billing_customer_references(reference_id,tenant_id,binding_id,provider_customer_id),
 CHECK((claim_token IS NULL)=(claim_until IS NULL)),
 CHECK((first_submitted_at IS NULL)=(replay_deadline IS NULL)),
 CHECK((dispatch_count=0)=(first_submitted_at IS NULL)),
 CHECK((state='succeeded' AND reference_id IS NOT NULL AND provider_customer_id IS NOT NULL AND confirmation IS NOT NULL)
  OR (state<>'succeeded' AND reference_id IS NULL AND provider_customer_id IS NULL AND confirmation IS NULL)),
 CHECK(state NOT IN ('prepared','cancelled') OR first_submitted_at IS NULL)
);
CREATE UNIQUE INDEX customer_operation_effective ON public.billing_customer_operations(tenant_id,binding_id)
 WHERE state NOT IN ('rejected','cancelled');
ALTER TABLE public.billing_customer_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_customer_operations FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.billing_customer_operations FROM PUBLIC,ceopro_app,ceopro_billing_setup,ceopro_billing_webhook;
GRANT SELECT ON public.billing_customer_operations TO ceopro_billing_setup,ceopro_trial_issuer;
GRANT INSERT,UPDATE ON public.billing_customer_operations TO ceopro_trial_issuer;
CREATE POLICY customer_operation_issuer ON public.billing_customer_operations TO ceopro_trial_issuer
 USING(tenant_id=public.get_current_tenant()) WITH CHECK(tenant_id=public.get_current_tenant());
CREATE POLICY customer_operation_reader ON public.billing_customer_operations FOR SELECT TO ceopro_billing_setup
 USING(tenant_id=public.get_current_tenant()
 AND public.keel_active_principal(nullif(current_setting('app.current_user_id',true),'')::uuid,tenant_id)
 AND EXISTS(SELECT FROM public.tenant_users m WHERE m.tenant_id=billing_customer_operations.tenant_id
  AND m.user_id=nullif(current_setting('app.current_user_id',true),'')::uuid
  AND m.role_key IN ('owner','admin','accountant') AND m.removed_at IS NULL AND m.platform_suspended_at IS NULL));

CREATE FUNCTION public.billing_customer_operation_guard() RETURNS trigger
 LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
 IF current_user<>'ceopro_trial_issuer' THEN
  RAISE EXCEPTION 'Restricted Customer command required' USING ERRCODE='42501'; END IF;
 IF TG_OP='UPDATE' THEN
  IF OLD.state IN ('succeeded','rejected','cancelled') OR NEW.version<>OLD.version+1
   OR (NEW.operation_id,NEW.tenant_id,NEW.binding_id,NEW.initiated_by,NEW.request_identity,NEW.idempotency_key,
       NEW.logical_request,NEW.transport_request,NEW.encoder_version,NEW.api_version,NEW.replay_supported,
       NEW.replay_window_seconds,NEW.dispatch_timeout_seconds,NEW.created_at)
   IS DISTINCT FROM
      (OLD.operation_id,OLD.tenant_id,OLD.binding_id,OLD.initiated_by,OLD.request_identity,OLD.idempotency_key,
       OLD.logical_request,OLD.transport_request,OLD.encoder_version,OLD.api_version,OLD.replay_supported,
       OLD.replay_window_seconds,OLD.dispatch_timeout_seconds,OLD.created_at)
   OR (OLD.first_submitted_at IS NOT NULL AND (NEW.first_submitted_at,NEW.replay_deadline)
       IS DISTINCT FROM (OLD.first_submitted_at,OLD.replay_deadline))
   OR NEW.dispatch_count NOT BETWEEN OLD.dispatch_count AND OLD.dispatch_count+1
   OR NOT (NEW.state=OLD.state
    OR (OLD.state='prepared' AND NEW.state IN ('submitted','cancelled','reconciliation_required'))
    OR (OLD.state='submitted' AND NEW.state IN ('unknown','succeeded','rejected','reconciliation_required'))
    OR (OLD.state='unknown' AND NEW.state IN ('submitted','succeeded','rejected','reconciliation_required'))
    OR (OLD.state='reconciliation_required' AND NEW.state IN ('succeeded','rejected')))
  THEN RAISE EXCEPTION 'Customer transition or identity conflict' USING ERRCODE='22023'; END IF;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.billing_customer_operation_guard() FROM PUBLIC;
CREATE TRIGGER customer_operation_guard BEFORE INSERT OR UPDATE ON public.billing_customer_operations
 FOR EACH ROW EXECUTE FUNCTION public.billing_customer_operation_guard();

CREATE FUNCTION public.billing_customer_operation(p_id uuid) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r public.billing_customer_operations; b jsonb; BEGIN
 PERFORM public.billing_reservation_principal();
 SELECT * INTO r FROM public.billing_customer_operations WHERE operation_id=p_id;
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT jsonb_build_object('binding_id',binding_id,'provider',provider,'environment',environment,
  'merchant_account_id',merchant_account_id) INTO b FROM public.billing_gateway_bindings WHERE binding_id=r.binding_id;
 RETURN to_jsonb(r)||jsonb_build_object('binding',b,'database_now',clock_timestamp());
END $$;

CREATE FUNCTION public.billing_customer_begin(p_id uuid,p_binding text,p_request text,p_logical text,p_transport text,
 p_encoder text,p_api text,p_supported boolean,p_window integer,p_timeout integer) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE t uuid:=public.get_current_tenant(); u uuid; r public.billing_customer_operations; BEGIN
 u:=public.billing_reservation_principal();
 -- Separate from trial locks; never take a person lock after this lock.
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_customer:'||t::text||':'||p_binding,0));
 SELECT * INTO r FROM public.billing_customer_operations
  WHERE tenant_id=t AND (operation_id=p_id OR (binding_id=p_binding AND request_identity=p_request));
 IF FOUND THEN
  IF (r.operation_id,r.binding_id,r.request_identity,r.logical_request,r.transport_request,r.encoder_version,r.api_version,
      r.replay_supported,r.replay_window_seconds,r.dispatch_timeout_seconds)
    IS DISTINCT FROM (p_id,p_binding,p_request,p_logical,p_transport,p_encoder,p_api,p_supported,p_window,p_timeout)
  THEN RAISE EXCEPTION 'Customer request replay conflict' USING ERRCODE='22023'; END IF;
  RETURN public.billing_customer_operation(r.operation_id);
 END IF;
 IF (public.billing_selected_gateway_binding()->>'binding_id') IS DISTINCT FROM p_binding
 THEN RAISE EXCEPTION 'Server-selected binding required' USING ERRCODE='42501'; END IF;
 IF EXISTS(SELECT FROM public.billing_customers WHERE tenant_id=t)
  OR EXISTS(SELECT FROM public.billing_checkout_attempts WHERE tenant_id=t AND gateway_binding_id IS NULL)
  OR EXISTS(SELECT FROM public.billing_customer_references WHERE tenant_id=t AND binding_id=p_binding)
 THEN RAISE EXCEPTION 'Existing Customer provenance requires review' USING ERRCODE='22023'; END IF;
 INSERT INTO public.billing_customer_operations(operation_id,tenant_id,binding_id,initiated_by,request_identity,
  idempotency_key,logical_request,transport_request,encoder_version,api_version,replay_supported,
  replay_window_seconds,dispatch_timeout_seconds)
 VALUES(p_id,t,p_binding,u,p_request,'keel-customer-'||p_id::text,p_logical,p_transport,p_encoder,p_api,p_supported,p_window,p_timeout);
 RETURN public.billing_customer_operation(p_id);
END $$;

CREATE FUNCTION public.billing_customer_command(p_id uuid,p_version bigint,p_action text,p_token uuid,p_payload jsonb DEFAULT '{}')
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r public.billing_customer_operations; ref public.billing_customer_references; n timestamptz;
 b jsonb; code text; BEGIN
 PERFORM public.billing_reservation_principal();
 SELECT * INTO r FROM public.billing_customer_operations WHERE operation_id=p_id FOR UPDATE;
 n:=clock_timestamp(); -- Evaluate leases after any row-lock wait, not before it.
 IF NOT FOUND OR p_version IS NULL OR r.version<>p_version OR r.state IN ('succeeded','rejected','cancelled')
 THEN RAISE EXCEPTION 'Customer operation stale or unavailable' USING ERRCODE='22023'; END IF;
 IF p_action='claim' THEN
  IF p_token IS NULL OR (r.claim_until IS NOT NULL AND r.claim_until>n)
  THEN RAISE EXCEPTION 'Customer operation already claimed' USING ERRCODE='55000'; END IF;
  UPDATE public.billing_customer_operations SET claim_token=p_token,claim_until=n+interval '30 seconds',
   version=version+1,updated_at=n WHERE operation_id=p_id;
  RETURN public.billing_customer_operation(p_id);
 END IF;
 IF p_token IS NULL OR r.claim_token IS DISTINCT FROM p_token OR r.claim_until<=n
 THEN RAISE EXCEPTION 'Customer execution claim stale' USING ERRCODE='55000'; END IF;
 IF p_action='authorize' THEN
  IF r.state<>'submitted' OR NOT r.replay_supported
    OR r.replay_deadline<=clock_timestamp()+make_interval(secs=>r.dispatch_timeout_seconds+2)
  THEN RAISE EXCEPTION 'Customer dispatch deadline unavailable' USING ERRCODE='55000'; END IF;
  RETURN public.billing_customer_operation(p_id);
 END IF;
 IF p_action='dispatch' THEN
  IF r.state NOT IN ('prepared','submitted','unknown') OR NOT r.replay_supported
    OR r.replay_window_seconds<=r.dispatch_timeout_seconds+2
    OR (r.replay_deadline IS NOT NULL AND r.replay_deadline<=n+make_interval(secs=>r.dispatch_timeout_seconds+2))
  THEN
   UPDATE public.billing_customer_operations SET state='reconciliation_required',
    last_error=CASE WHEN NOT replay_supported THEN 'unsupported_capability' ELSE 'replay_expired' END,
    claim_token=NULL,claim_until=NULL,version=version+1,updated_at=n WHERE operation_id=p_id;
  ELSE
   UPDATE public.billing_customer_operations SET state='submitted',dispatch_count=dispatch_count+1,
    first_submitted_at=coalesce(first_submitted_at,n),
    replay_deadline=coalesce(replay_deadline,n+make_interval(secs=>replay_window_seconds)),
    version=version+1,updated_at=n WHERE operation_id=p_id;
  END IF;
 ELSIF p_action='cancel' THEN
  IF r.state<>'prepared' OR r.first_submitted_at IS NOT NULL
  THEN RAISE EXCEPTION 'Possible submission cannot be cancelled' USING ERRCODE='22023'; END IF;
  UPDATE public.billing_customer_operations SET state='cancelled',claim_token=NULL,claim_until=NULL,
   version=version+1,updated_at=n WHERE operation_id=p_id;
 ELSIF p_action='fail' THEN
  code:=p_payload->>'code';
  IF r.state<>'submitted' OR code NOT IN ('rejected','unavailable','outcome_unknown','not_found','unsupported_capability')
    OR code IS NULL THEN RAISE EXCEPTION 'Invalid Customer failure evidence' USING ERRCODE='22023'; END IF;
  -- A rejection of a replay cannot erase the uncertainty of an earlier dispatch.
  UPDATE public.billing_customer_operations SET state=CASE WHEN code='rejected' AND dispatch_count=1
   THEN 'rejected' ELSE 'unknown' END,last_error=code,claim_token=NULL,claim_until=NULL,
   version=version+1,updated_at=n WHERE operation_id=p_id;
 ELSIF p_action='reconcile' THEN
  code:=p_payload->>'code';
  IF code IS NULL OR code NOT IN ('inconclusive','conflict','replay_expired','unsupported_capability','unavailable')
  THEN RAISE EXCEPTION 'Invalid reconciliation category' USING ERRCODE='22023'; END IF;
  UPDATE public.billing_customer_operations SET state='reconciliation_required',last_error=code,
   claim_token=NULL,claim_until=NULL,version=version+1,updated_at=n WHERE operation_id=p_id;
 ELSIF p_action IN ('confirm','non_creation') THEN
  SELECT public.billing_customer_operation(p_id)->'binding' INTO b;
  IF p_payload->'binding' IS DISTINCT FROM b OR p_payload->>'tenant_id' IS DISTINCT FROM r.tenant_id::text
    OR p_payload->>'operation_id' IS DISTINCT FROM p_id::text OR nullif(p_payload->>'evidence_id','') IS NULL
    OR r.first_submitted_at IS NULL
  THEN RAISE EXCEPTION 'Customer evidence association conflict' USING ERRCODE='22023'; END IF;
  -- Trusted adapter verification is an application boundary, never a client flag.
  IF p_action='non_creation' THEN
   UPDATE public.billing_customer_operations SET state='rejected',last_error='non_creation',claim_token=NULL,claim_until=NULL,
    version=version+1,updated_at=n WHERE operation_id=p_id;
  ELSE
   IF nullif(btrim(p_payload->>'customer_id'),'') IS NULL
    OR p_payload->>'evidence_kind' IS NULL OR p_payload->>'evidence_kind' NOT IN ('create_response','retrieved','recovered')
   THEN RAISE EXCEPTION 'Verified Customer provenance required' USING ERRCODE='22023'; END IF;
   INSERT INTO public.billing_customer_references(tenant_id,binding_id,provider_customer_id)
    VALUES(r.tenant_id,r.binding_id,p_payload->>'customer_id') ON CONFLICT(tenant_id,binding_id) DO NOTHING;
   SELECT * INTO ref FROM public.billing_customer_references WHERE tenant_id=r.tenant_id AND binding_id=r.binding_id;
   IF ref.provider_customer_id IS DISTINCT FROM p_payload->>'customer_id'
   THEN RAISE EXCEPTION 'Customer mapping conflict' USING ERRCODE='22023'; END IF;
   UPDATE public.billing_customer_operations SET state='succeeded',reference_id=ref.reference_id,
    provider_customer_id=ref.provider_customer_id,confirmation=p_payload,last_error=NULL,
    claim_token=NULL,claim_until=NULL,version=version+1,updated_at=n WHERE operation_id=p_id;
  END IF;
 ELSE RAISE EXCEPTION 'Unsupported Customer operation' USING ERRCODE='22023'; END IF;
 RETURN public.billing_customer_operation(p_id);
END $$;

-- Same reviewed NOLOGIN owner and ACL-before-owner-transfer pattern as C.2B.
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='ceopro_trial_issuer' AND NOT rolcanlogin AND NOT rolsuper
  AND NOT rolbypassrls AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolinherit AND NOT rolreplication)
 OR EXISTS(SELECT FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='ceopro_trial_issuer'))
 OR has_schema_privilege('ceopro_trial_issuer','public','CREATE')
 THEN RAISE EXCEPTION 'Restricted issuer prerequisites required'; END IF;
END $$;
REVOKE ALL ON FUNCTION public.billing_customer_operation(uuid),
 public.billing_customer_begin(uuid,text,text,text,text,text,text,boolean,integer,integer),
 public.billing_customer_command(uuid,bigint,text,uuid,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_customer_operation(uuid),
 public.billing_customer_begin(uuid,text,text,text,text,text,text,boolean,integer,integer),
 public.billing_customer_command(uuid,bigint,text,uuid,jsonb) TO ceopro_billing_setup;
GRANT SELECT ON public.billing_customers TO ceopro_trial_issuer;
CREATE POLICY customer_operation_legacy_read ON public.billing_customers FOR SELECT TO ceopro_trial_issuer
 USING(tenant_id=public.get_current_tenant());
GRANT CREATE ON SCHEMA public TO ceopro_trial_issuer;
ALTER FUNCTION public.billing_customer_operation(uuid) OWNER TO ceopro_trial_issuer;
ALTER FUNCTION public.billing_customer_begin(uuid,text,text,text,text,text,text,boolean,integer,integer) OWNER TO ceopro_trial_issuer;
ALTER FUNCTION public.billing_customer_command(uuid,bigint,text,uuid,jsonb) OWNER TO ceopro_trial_issuer;
REVOKE CREATE ON SCHEMA public FROM ceopro_trial_issuer;
