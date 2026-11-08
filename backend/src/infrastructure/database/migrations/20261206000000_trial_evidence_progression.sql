-- Dormant A2: append-only, monotone trial evidence within one original operation.
-- No new runtime role, membership, consent writer or activation authority.
CREATE FUNCTION public.billing_confirmation_progresses(p_old jsonb,p_new jsonb) RETURNS boolean
 LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE a jsonb:=public.billing_confirmation_semantic(p_old);b jsonb:=public.billing_confirmation_semantic(p_new);
 k text;v jsonb;before_value text;after_value text;section text;x jsonb;y jsonb;fallback boolean; BEGIN
 IF jsonb_typeof(a) IS DISTINCT FROM 'object' OR jsonb_typeof(b) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
 -- Positive identities, commercial amounts, trial/period dates, settlement and
 -- cancellation facts never change or disappear. Only missing facts may fill in.
 FOR k,v IN SELECT * FROM jsonb_each(a-ARRAY['checkout_state','subscription_state','payment_method','recurring_authority','capabilities']) LOOP
  IF v<>'null'::jsonb AND v IS DISTINCT FROM b->k THEN RETURN false; END IF;
 END LOOP;
 FOR k IN SELECT unnest(ARRAY['checkout_state','subscription_state']) LOOP
  before_value:=a->>k;after_value:=b->>k;
  IF before_value IS DISTINCT FROM after_value AND NOT coalesce(
   (before_value='unknown' AND after_value=ANY(CASE k WHEN 'checkout_state' THEN ARRAY['open','complete'] ELSE ARRAY['pending','trialing'] END))
   OR (k='checkout_state' AND before_value='open' AND after_value='complete')
   OR (k='subscription_state' AND before_value='pending' AND after_value='trialing'),false)
  THEN RETURN false; END IF;
 END LOOP;
 -- Subscription provenance is an unresolved setup source, not a positive
 -- SetupIntent identity. It may refine only to a correlated setup mechanism.
 fallback:=coalesce(a#>>'{recurring_authority,kind}'='unknown'
  AND a#>>'{recurring_authority,source}'=a->>'subscription'
  AND a#>>'{recurring_authority,readiness}' IN ('unknown','attached')
  AND b#>>'{recurring_authority,kind}'='payment_method_setup'
  AND nullif(b#>>'{recurring_authority,source}','') IS NOT NULL
  AND b#>>'{payment_method,source}'=b#>>'{recurring_authority,source}',false);
 FOR section IN SELECT unnest(ARRAY['payment_method','recurring_authority']) LOOP
  x:=a->section;y:=b->section;
  IF x IS NULL OR x='null'::jsonb THEN CONTINUE; END IF;
  IF jsonb_typeof(y) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
  FOR k,v IN SELECT * FROM jsonb_each(x) LOOP
   before_value:=x->>k;after_value:=y->>k;
   IF k='readiness' THEN
    IF before_value IS DISTINCT FROM after_value AND NOT coalesce(
     (before_value='unknown' AND after_value IN ('attached','pending_setup','reusable_authority_confirmed'))
     OR (before_value='attached' AND after_value IN ('pending_setup','reusable_authority_confirmed'))
     OR (before_value='pending_setup' AND after_value='reusable_authority_confirmed'),false)
    THEN RETURN false; END IF;
   ELSIF k='kind' AND before_value='unknown' AND after_value='payment_method_setup' THEN CONTINUE;
   ELSIF k='source' AND fallback AND before_value=a->>'subscription' THEN CONTINUE;
   ELSIF v<>'null'::jsonb AND v IS DISTINCT FROM y->k THEN RETURN false;
   END IF;
  END LOOP;
 END LOOP;
 FOR k,v IN SELECT * FROM jsonb_each(coalesce(nullif(a->'capabilities','null'::jsonb),'{}'::jsonb)) LOOP
  IF v IS DISTINCT FROM b#>ARRAY['capabilities',k] AND NOT
   (v='"unknown"'::jsonb AND coalesce(b#>>ARRAY['capabilities',k],'') IN ('supported','unsupported','requires_approval'))
  THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION public.billing_confirmation_progresses(jsonb,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_confirmation_progresses(jsonb,jsonb) TO ceopro_observation_owner;
GRANT CREATE ON SCHEMA public TO ceopro_confirmation_owner;
ALTER FUNCTION public.billing_confirmation_progresses(jsonb,jsonb) OWNER TO ceopro_confirmation_owner;
REVOKE CREATE ON SCHEMA public FROM ceopro_confirmation_owner;

CREATE OR REPLACE FUNCTION public.billing_confirmation_attest(p_id uuid,p_operation uuid,p_version bigint,p_token uuid,p_consent uuid,
 p_request jsonb,p_evidence jsonb,p_observed timestamptz,p_completed timestamptz,p_expires timestamptz) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE o public.billing_observation_operations;v public.billing_verification_observations;r public.billing_trial_checkouts;
 c public.billing_trial_consents;a public.billing_trial_attestations;u uuid;n timestamptz;clean jsonb;baseline jsonb;cap text; BEGIN
 u:=public.billing_confirmation_principal('ceopro_trial_attestor');
 SELECT * INTO o FROM public.billing_observation_operations WHERE operation_id=p_operation FOR UPDATE;n:=clock_timestamp();
 IF NOT FOUND OR p_version IS NULL OR p_token IS NULL OR o.version<>p_version OR o.claim_token IS DISTINCT FROM p_token OR o.claim_until<=n
 OR p_request IS DISTINCT FROM o.request OR o.request_kind<>'trial_checkout'
 THEN RAISE EXCEPTION 'Original live observation claim required' USING ERRCODE='55000'; END IF;
 SELECT * INTO r FROM public.billing_trial_checkouts WHERE attempt_id=o.attempt_id;
 SELECT * INTO v FROM public.billing_verification_observations WHERE observation_id=o.last_observation_id;
 SELECT * INTO c FROM public.billing_trial_consents WHERE consent_id=p_consent AND operation_id=o.operation_id;
 IF o.customer_operation_id IS NULL OR NOT EXISTS(SELECT FROM public.billing_customer_operations co WHERE co.operation_id=o.customer_operation_id
  AND co.tenant_id=o.tenant_id AND co.binding_id=o.binding_id AND co.reference_id=o.reference_id AND co.provider_customer_id=o.provider_customer_id AND co.state='succeeded')
 OR v.observation_id IS NULL OR v.source<>'authoritative_lookup' OR v.outcome NOT IN ('pending','verified')
 OR coalesce(v.evidence#>>'{recurring_authority,consent}','unknown') NOT IN ('unknown','pending')
 OR v.observed_at<n-interval '5 minutes' OR p_observed IS NULL OR p_observed<n-interval '5 minutes' OR p_observed>n+interval '30 seconds'
 OR c.consent_id IS NULL OR c.actor_id<>r.started_by_user_id OR c.provider_customer_id<>o.provider_customer_id
 OR r.state<>'pending' OR p_completed IS NULL OR p_expires IS NULL OR p_completed>n OR p_completed>p_expires OR p_expires<=n
 THEN RAISE EXCEPTION 'Fresh trusted provenance and consent required' USING ERRCODE='22023'; END IF;
 -- Only explicit trusted local consent differs from the provider-only B3 read.
 clean:=p_evidence #- '{recurring_authority,consent_reference}'::text[] #- '{recurring_authority,consent_terms_revision}'::text[];
 clean:=jsonb_set(clean,'{recurring_authority,consent}','"unknown"'::jsonb);
 baseline:=v.evidence #- '{recurring_authority,consent_reference}'::text[] #- '{recurring_authority,consent_terms_revision}'::text[];
 baseline:=jsonb_set(baseline,'{recurring_authority,consent}','"unknown"'::jsonb);
 PERFORM public.billing_observation_evidence(clean);
 IF public.billing_confirmation_semantic(clean) IS DISTINCT FROM public.billing_confirmation_semantic(baseline)
 OR EXISTS(SELECT FROM public.billing_verification_observations h WHERE h.operation_id=o.operation_id AND
  (h.outcome='conflict' OR NOT public.billing_confirmation_progresses(h.evidence,v.evidence)))
 THEN RAISE EXCEPTION 'Unresolved material evidence conflict' USING ERRCODE='22023'; END IF;
 IF p_evidence->>'customer' IS DISTINCT FROM o.provider_customer_id OR p_evidence->>'checkout' IS DISTINCT FROM o.provider_checkout_id
 OR nullif(p_evidence->>'subscription','') IS NULL OR (o.provider_subscription_id IS NOT NULL AND p_evidence->>'subscription'<>o.provider_subscription_id)
 OR p_evidence->>'checkout_state' IS DISTINCT FROM 'complete' OR p_evidence->>'subscription_state' IS DISTINCT FROM 'trialing'
 OR p_evidence->>'cancel_at_period_end' IS DISTINCT FROM 'false' OR p_evidence->>'cancelled_at' IS NOT NULL
 OR p_evidence#>>'{recurring_authority,readiness}' IS DISTINCT FROM 'reusable_authority_confirmed'
 OR coalesce(p_evidence#>>'{recurring_authority,kind}','unknown') NOT IN ('payment_method_setup','mandate','provider_agreement')
 OR nullif(p_evidence#>>'{recurring_authority,source}','') IS NULL
 OR p_evidence#>>'{recurring_authority,consent}' IS DISTINCT FROM 'recorded'
 OR p_evidence#>>'{recurring_authority,consent_reference}' IS DISTINCT FROM c.agreement_reference
 OR p_evidence#>>'{recurring_authority,consent_terms_revision}' IS DISTINCT FROM c.agreement_revision
 OR (p_evidence->>'payment_method' IS NOT NULL AND p_evidence#>>'{payment_method,readiness}' IS DISTINCT FROM 'reusable_authority_confirmed')
 THEN RAISE EXCEPTION 'Complete recurring authority required' USING ERRCODE='22023'; END IF;
 FOREACH cap IN ARRAY ARRAY['hosted_checkout','reusable_payment_method','setup_without_charge','off_session_recurring','trial_subscription_setup','authenticated_webhooks','authoritative_reconciliation','idempotent_submission','cancellation'] LOOP
  IF p_evidence#>>ARRAY['capabilities',cap] IS DISTINCT FROM 'supported' THEN RAISE EXCEPTION 'Required capability unavailable' USING ERRCODE='22023'; END IF;
 END LOOP;
 IF (p_evidence#>>'{terms,amount}')::numeric IS DISTINCT FROM r.approved_amount
 OR (p_evidence#>>'{terms,currency}') IS DISTINCT FROM r.currency
 OR (p_evidence#>>'{terms,interval_months}')::int IS DISTINCT FROM r.interval_months
 OR (p_evidence#>>'{terms,quantity}')::int IS DISTINCT FROM 1
 OR p_evidence#>>'{terms,price}' IS DISTINCT FROM r.provider_price_id
 OR (p_evidence#>>'{trial,ends_at}')::timestamptz IS NULL OR (p_evidence#>>'{trial,started_at}')::timestamptz IS NULL
 OR (p_evidence#>>'{trial,ends_at}')::timestamptz-(p_evidence#>>'{trial,started_at}')::timestamptz<>make_interval(days=>r.trial_duration_days)
 OR (p_evidence#>>'{trial,cutoff}')::timestamptz IS DISTINCT FROM (p_evidence#>>'{trial,ends_at}')::timestamptz
 OR (p_evidence#>>'{trial,started_at}')::timestamptz<r.created_at-interval '30 seconds'
 OR (p_evidence#>>'{trial,started_at}')::timestamptz>p_observed
 OR (p_evidence#>>'{trial,started_at}')::timestamptz>p_completed
 OR c.accepted_at>(p_evidence#>>'{trial,started_at}')::timestamptz
 OR (p_evidence#>>'{trial,ends_at}')::timestamptz<=n
 THEN RAISE EXCEPTION 'Frozen commercial and trial terms required' USING ERRCODE='22023'; END IF;
 SELECT * INTO a FROM public.billing_trial_attestations WHERE attestation_id=p_id;
 IF FOUND THEN
  IF (a.operation_id,a.claim_version,a.claim_token,a.consent_id,a.request,a.evidence,a.observed_at,a.checkout_completed_at,a.checkout_expires_at)
   IS DISTINCT FROM (p_operation,p_version,p_token,p_consent,p_request,p_evidence,p_observed,p_completed,p_expires)
  THEN RAISE EXCEPTION 'Attestation replay conflict' USING ERRCODE='22023'; END IF;RETURN to_jsonb(a);
 END IF;
 INSERT INTO public.billing_trial_attestations(attestation_id,operation_id,tenant_id,binding_id,consent_id,observation_id,claim_version,claim_token,
 request,evidence,history_digest,observed_at,checkout_completed_at,checkout_expires_at)
 VALUES(p_id,p_operation,o.tenant_id,o.binding_id,p_consent,v.observation_id,p_version,p_token,p_request,p_evidence,
 public.billing_confirmation_history(p_operation),p_observed,p_completed,p_expires) RETURNING * INTO a;RETURN to_jsonb(a);
END $$;

CREATE OR REPLACE FUNCTION public.billing_observation_record(p_id uuid,p_version bigint,p_token uuid,p_observation uuid,p_source text,p_receipt uuid,
 p_reference text,p_observed timestamptz,p_adapter text,p_api text,p_outcome text,p_evidence jsonb,p_request jsonb) RETURNS jsonb
 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
DECLARE r public.billing_observation_operations;o public.billing_verification_observations;old public.billing_verification_observations;e public.billing_observation_receipts;
 n timestamptz;d text;conflict boolean; BEGIN
 PERFORM public.billing_observation_principal();PERFORM public.billing_observation_evidence(p_evidence);
 d:='sha256:'||encode(sha256(convert_to(p_evidence::text,'UTF8')),'hex');
 SELECT * INTO r FROM public.billing_observation_operations WHERE operation_id=p_id FOR UPDATE;n:=clock_timestamp();
 IF NOT FOUND THEN RAISE EXCEPTION 'Observation unavailable' USING ERRCODE='22023'; END IF;
 IF p_request IS DISTINCT FROM r.request THEN RAISE EXCEPTION 'Original observation request scope required' USING ERRCODE='22023'; END IF;
 SELECT * INTO o FROM public.billing_verification_observations WHERE observation_id=p_observation;
 IF FOUND THEN
  IF (o.operation_id,o.claim_version,o.claim_token,o.source,o.receipt_id,o.provenance_reference,o.observed_at,o.adapter_version,o.api_version,o.outcome,o.evidence)
   IS DISTINCT FROM (p_id,p_version,p_token,p_source,p_receipt,p_reference,p_observed,p_adapter,p_api,p_outcome,p_evidence)
  THEN RAISE EXCEPTION 'Observation identity replay conflict' USING ERRCODE='22023'; END IF;RETURN to_jsonb(o);
 END IF;
 IF p_version IS NULL OR r.version<>p_version OR p_token IS NULL OR r.claim_token IS DISTINCT FROM p_token OR r.claim_until<=n
 THEN RAISE EXCEPTION 'Observation execution stale' USING ERRCODE='55000'; END IF;
 IF p_observed IS NULL OR p_observed<n-interval '5 minutes' OR p_observed>n+interval '30 seconds' OR p_outcome NOT IN ('verified','pending','conflict','unavailable','unsupported') OR p_outcome IS NULL
 THEN RAISE EXCEPTION 'Observation freshness or outcome unavailable' USING ERRCODE='22023'; END IF;
 IF p_source='authenticated_notification' THEN
  SELECT * INTO e FROM public.billing_observation_receipts WHERE receipt_id=p_receipt AND operation_id=p_id;
  IF NOT FOUND OR e.provider_event_id IS DISTINCT FROM p_reference OR p_outcome='verified'
  THEN RAISE EXCEPTION 'Authenticated notification provenance required' USING ERRCODE='22023'; END IF;
 ELSIF p_source='authoritative_lookup' THEN
  IF p_receipt IS NOT NULL OR p_reference IS DISTINCT FROM coalesce(r.provider_checkout_id,r.provider_subscription_id)
  THEN RAISE EXCEPTION 'Lookup cannot impersonate a notification' USING ERRCODE='22023'; END IF;
 ELSE RAISE EXCEPTION 'Explicit evidence source required' USING ERRCODE='22023'; END IF;
 IF (p_evidence->>'customer' IS NOT NULL AND p_evidence->>'customer' IS DISTINCT FROM r.provider_customer_id)
 OR (p_evidence->>'checkout' IS NOT NULL AND p_evidence->>'checkout' IS DISTINCT FROM r.provider_checkout_id)
 OR (r.provider_subscription_id IS NOT NULL AND p_evidence->>'subscription' IS NOT NULL AND p_evidence->>'subscription' IS DISTINCT FROM r.provider_subscription_id)
 OR (r.request_kind='trial_checkout' AND p_outcome='verified')
 THEN RAISE EXCEPTION 'Observation association or readiness conflict' USING ERRCODE='22023'; END IF;
 IF r.request_kind='trial_checkout' AND p_evidence->>'terms' IS NOT NULL AND (
  (p_evidence#>>'{terms,amount}')::numeric IS DISTINCT FROM (r.request#>>'{trial_terms,amount}')::numeric
  OR ((p_evidence->'terms')-'amount') IS DISTINCT FROM ((r.request->'trial_terms')-'plan_key'-'catalog_revision_id'-'trial_duration_days'-'amount'))
 THEN RAISE EXCEPTION 'Frozen terms conflict' USING ERRCODE='22023'; END IF;
 SELECT * INTO old FROM public.billing_verification_observations WHERE observation_id=r.last_observation_id;
 IF r.request_kind='trial_checkout' AND EXISTS(SELECT FROM public.billing_verification_observations h
  WHERE h.operation_id=p_id AND h.observed_at>p_observed)
 THEN RAISE EXCEPTION 'Out-of-order trial observation' USING ERRCODE='22023'; END IF;
 -- Compare ALL immutable history: an incomplete intervening read must not hide
 -- an earlier positive identity or financial contradiction. No row is rewritten.
 conflict:=r.has_conflict OR p_outcome='conflict' OR CASE WHEN r.request_kind='trial_checkout' THEN
  EXISTS(SELECT FROM public.billing_verification_observations h WHERE h.operation_id=p_id
   AND NOT public.billing_confirmation_progresses(h.evidence,p_evidence))
 ELSE old.observation_id IS NOT NULL AND public.billing_confirmation_semantic(old.evidence) IS DISTINCT FROM public.billing_confirmation_semantic(p_evidence) END;
 INSERT INTO public.billing_verification_observations(observation_id,operation_id,tenant_id,binding_id,source,receipt_id,provenance_reference,observed_at,adapter_version,api_version,outcome,evidence,evidence_digest,claim_version,claim_token)
 VALUES(p_observation,p_id,r.tenant_id,r.binding_id,p_source,p_receipt,p_reference,p_observed,p_adapter,p_api,p_outcome,p_evidence,d,p_version,p_token) RETURNING * INTO o;
 UPDATE public.billing_observation_operations SET state=CASE WHEN conflict THEN 'reconciliation_required' ELSE 'observed' END,has_conflict=conflict,
  last_observation_id=p_observation,claim_token=NULL,claim_until=NULL,version=version+1,updated_at=n WHERE operation_id=p_id;
 RETURN to_jsonb(o);
END $$;
