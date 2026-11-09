-- One original Paddle Customer send, with no provider replay claim.
-- Existing role ownership and ACL remain unchanged; no new grants or tables.
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='ceopro_trial_issuer' AND NOT rolcanlogin AND NOT rolsuper
  AND NOT rolbypassrls AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolinherit AND NOT rolreplication)
 OR EXISTS(SELECT FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='ceopro_trial_issuer'))
 OR has_schema_privilege('ceopro_trial_issuer','public','CREATE')
 THEN RAISE EXCEPTION 'Restricted issuer prerequisites required' USING ERRCODE='42501'; END IF;
END $$;
CREATE OR REPLACE FUNCTION public.billing_customer_command(p_id uuid,p_version bigint,p_action text,p_token uuid,p_payload jsonb DEFAULT '{}')
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
  IF r.state<>'submitted' OR (NOT r.replay_supported AND NOT (r.encoder_version='paddle-customer-v1-single-send' AND r.dispatch_count=1 AND r.api_version='1' AND r.replay_window_seconds=0 AND EXISTS(SELECT FROM public.billing_gateway_bindings g WHERE g.binding_id=r.binding_id AND g.provider='paddle' AND g.environment='test')))
    OR r.replay_deadline<=clock_timestamp()+make_interval(secs=>r.dispatch_timeout_seconds+2)
  THEN RAISE EXCEPTION 'Customer dispatch deadline unavailable' USING ERRCODE='55000'; END IF;
  RETURN public.billing_customer_operation(p_id);
 END IF;
 IF p_action='dispatch' THEN
  IF r.encoder_version='paddle-customer-v1-single-send' AND r.api_version='1'
   AND NOT r.replay_supported AND r.replay_window_seconds=0 AND r.dispatch_timeout_seconds=5
   AND EXISTS(SELECT FROM public.billing_gateway_bindings g WHERE g.binding_id=r.binding_id AND g.provider='paddle' AND g.environment='test') THEN
   IF r.state<>'prepared' OR r.first_submitted_at IS NOT NULL OR r.dispatch_count<>0
   THEN RAISE EXCEPTION 'Paddle submission already elected' USING ERRCODE='55000'; END IF;
   UPDATE public.billing_customer_operations SET state='submitted',dispatch_count=1,first_submitted_at=n,
    replay_deadline=n+interval '30 seconds',version=version+1,updated_at=n WHERE operation_id=p_id;
   RETURN public.billing_customer_operation(p_id);
  END IF;
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
