-- Phase 1A. Forward-only; apply with existing schema-owner migration runner.
-- No existing identity, commercial assignment or historical record is replaced.
ALTER TABLE users ADD COLUMN IF NOT EXISTS platform_disabled_at timestamptz;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS platform_suspended_at timestamptz;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS platform_notes text NOT NULL DEFAULT '';
ALTER TABLE tenant_users ADD COLUMN IF NOT EXISTS platform_suspended_at timestamptz;

CREATE TABLE keel_pending_registrations (
 email text PRIMARY KEY CHECK (email=lower(btrim(email))),
 password_hash text, full_name text NOT NULL, business_name text NOT NULL,
 country_code char(2) NOT NULL CHECK(country_code ~ '^[A-Z]{2}$'),
 currency char(3) NOT NULL CHECK(currency ~ '^[A-Z]{3}$'), timezone text NOT NULL,
 request_hash char(64) NOT NULL UNIQUE, code_hash char(64) NOT NULL,
 expires_at timestamptz NOT NULL, attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
 send_count integer NOT NULL DEFAULT 1 CHECK(send_count>0), sent_window_at timestamptz NOT NULL DEFAULT now(),
 verified_at timestamptz, user_id uuid REFERENCES users(user_id) ON DELETE SET NULL, tenant_id uuid REFERENCES companies(tenant_id) ON DELETE SET NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE keel_pending_registrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE keel_pending_registrations FORCE ROW LEVEL SECURITY;
REVOKE ALL ON keel_pending_registrations FROM PUBLIC,ceopro_app;
CREATE POLICY internal_owner ON keel_pending_registrations TO PUBLIC
 USING(current_user=pg_get_userbyid((SELECT relowner FROM pg_class WHERE oid='public.keel_pending_registrations'::regclass)))
 WITH CHECK(current_user=pg_get_userbyid((SELECT relowner FROM pg_class WHERE oid='public.keel_pending_registrations'::regclass)));

CREATE OR REPLACE FUNCTION keel_pending_registration(action text, p jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE r keel_pending_registrations%ROWTYPE; uid uuid; tid uuid; send_counter integer; send_window timestamptz; email_key text:=lower(btrim(p->>'email'));
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_signup:'||email_key,0));
 SELECT * INTO r FROM keel_pending_registrations WHERE email=email_key FOR UPDATE;
 IF action='register' THEN
   IF EXISTS(SELECT 1 FROM users WHERE lower(email)=email_key) OR
      (r.email IS NOT NULL AND r.expires_at>now()) THEN RETURN jsonb_build_object('status','conflict'); END IF;
   -- Expired pending data may be replaced; never an existing identity or a live pending password.
   DELETE FROM keel_pending_registrations WHERE email=email_key;
   INSERT INTO keel_pending_registrations(email,password_hash,full_name,business_name,country_code,currency,timezone,request_hash,code_hash,expires_at)
    VALUES(email_key,p->>'password_hash',p->>'full_name',p->>'business_name',p->>'country_code',p->>'currency',p->>'timezone',p->>'request_hash',p->>'code_hash',(p->>'expires_at')::timestamptz);
   RETURN jsonb_build_object('status','pending');
 END IF;
 IF r.email IS NULL OR r.request_hash IS DISTINCT FROM p->>'request_hash' THEN
   RETURN jsonb_build_object('status','invalid');
 END IF;
 -- A consumed challenge cannot mint another session or start another trial.
 IF r.verified_at IS NOT NULL THEN RETURN jsonb_build_object('status','verified','created',false); END IF;
 IF r.expires_at<=clock_timestamp() THEN RETURN jsonb_build_object('status','invalid'); END IF;
 IF action='resend' THEN
   send_counter:=r.send_count;send_window:=r.sent_window_at;
   IF send_window + make_interval(secs=>(p->>'send_window_seconds')::integer)<=now() THEN
     send_counter:=0; send_window:=now();
   END IF;
   IF send_counter >= (p->>'max_sends')::integer THEN RETURN jsonb_build_object('status','limited'); END IF;
   UPDATE keel_pending_registrations SET code_hash=p->>'code_hash', send_count=send_counter+1,
     sent_window_at=send_window WHERE email=email_key;
   -- Wrong-code attempts never reset via resend; challenge lifetime is not extended.
   RETURN jsonb_build_object('status','pending');
 ELSIF action='verify' THEN
   IF r.attempts >= (p->>'max_attempts')::integer THEN RETURN jsonb_build_object('status','limited'); END IF;
   IF r.code_hash IS DISTINCT FROM p->>'code_hash' THEN
     UPDATE keel_pending_registrations SET attempts=attempts+1 WHERE email=email_key;
     RETURN jsonb_build_object('status','invalid');
   END IF;
   IF EXISTS(SELECT 1 FROM users WHERE lower(email)=email_key) THEN RETURN jsonb_build_object('status','conflict'); END IF;
   uid:=gen_random_uuid();tid:=gen_random_uuid();
   INSERT INTO users(user_id,email,password_hash,full_name,email_verified_at)
     VALUES(uid,email_key,r.password_hash,r.full_name,now());
   INSERT INTO companies(tenant_id,business_name,country_code,primary_currency,supported_currencies,timezone,is_demo)
     VALUES(tid,r.business_name,r.country_code,r.currency,ARRAY[r.currency::varchar],r.timezone,email_key LIKE '%.example');
   INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(tid,uid,'owner');
   UPDATE keel_pending_registrations SET verified_at=now(),password_hash=NULL,user_id=uid,tenant_id=tid WHERE email=email_key;
   RETURN jsonb_build_object('status','created','created',true,'user_id',uid,'tenant_id',tid,'email',email_key,
     'full_name',r.full_name,'business_name',r.business_name);
 END IF;
 RAISE EXCEPTION 'Unknown registration operation' USING ERRCODE='22023';
END $$;
REVOKE ALL ON FUNCTION keel_pending_registration(text,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION keel_pending_registration(text,jsonb) TO ceopro_app;

CREATE OR REPLACE FUNCTION keel_active_principal(uid uuid,tid uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT uid<>'00000000-0000-0000-0000-000000000000'::uuid AND EXISTS(
 SELECT 1 FROM users u JOIN tenant_users tu ON tu.user_id=u.user_id JOIN companies c ON c.tenant_id=tu.tenant_id
 WHERE u.user_id=uid AND c.tenant_id=tid AND u.platform_disabled_at IS NULL
 AND c.platform_suspended_at IS NULL AND c.deleted_at IS NULL AND tu.removed_at IS NULL AND tu.platform_suspended_at IS NULL);
$$;
REVOKE ALL ON FUNCTION keel_active_principal(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION keel_active_principal(uuid,uuid) TO ceopro_app;
-- Preserve nil-UUID trusted background context; it cannot enter HTTP principal validation.
CREATE OR REPLACE FUNCTION get_current_tenant() RETURNS uuid
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE tid uuid:=nullif(current_setting('app.current_tenant_id',true),'')::uuid;
 uid uuid:=nullif(current_setting('app.current_user_id',true),'')::uuid;
BEGIN
 IF tid IS NULL OR uid IS NULL THEN RETURN NULL; END IF;
 IF uid='00000000-0000-0000-0000-000000000000'::uuid THEN
  IF EXISTS(SELECT 1 FROM companies WHERE tenant_id=tid AND platform_suspended_at IS NULL AND deleted_at IS NULL) THEN RETURN tid; END IF;
  RETURN NULL;
 END IF;
 IF keel_active_principal(uid,tid) THEN RETURN tid; END IF;
 RETURN NULL;
END $$;
CREATE OR REPLACE FUNCTION auth_lookup_user_memberships(p_user_id uuid)
RETURNS TABLE(tenant_id uuid,role_key varchar,business_name varchar)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT tu.tenant_id,tu.role_key,c.business_name FROM tenant_users tu JOIN companies c USING(tenant_id)
 JOIN users u ON u.user_id=tu.user_id WHERE tu.user_id=p_user_id AND tu.removed_at IS NULL AND tu.platform_suspended_at IS NULL
 AND c.platform_suspended_at IS NULL AND c.deleted_at IS NULL AND u.platform_disabled_at IS NULL ORDER BY tu.joined_at;
$$;
REVOKE ALL ON FUNCTION auth_lookup_user_memberships(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_lookup_user_memberships(uuid) TO ceopro_app;

CREATE TABLE keel_platform_workspace(singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),tenant_id uuid NOT NULL UNIQUE REFERENCES companies(tenant_id));
CREATE TABLE keel_platform_members(user_id uuid PRIMARY KEY REFERENCES users(user_id),role_key text NOT NULL CHECK(role_key IN('owner','admin')),
 status text NOT NULL DEFAULT 'active' CHECK(status IN('active','suspended','removed')),updated_at timestamptz NOT NULL DEFAULT now());
CREATE UNIQUE INDEX keel_one_platform_owner ON keel_platform_members(role_key) WHERE role_key='owner' AND status='active';
CREATE TABLE keel_platform_invitations(invitation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),email text NOT NULL,
 token_hash char(64) NOT NULL UNIQUE,expires_at timestamptz NOT NULL,created_by uuid NOT NULL REFERENCES users(user_id),
 accepted_by uuid REFERENCES users(user_id),accepted_at timestamptz,canceled_at timestamptz,created_at timestamptz NOT NULL DEFAULT now());
CREATE UNIQUE INDEX keel_one_pending_platform_invitation ON keel_platform_invitations(lower(email)) WHERE accepted_at IS NULL AND canceled_at IS NULL;
CREATE TABLE keel_platform_audit(audit_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),actor_user_id uuid,
 actor_role text,action text NOT NULL,subject text NOT NULL,old_value jsonb,new_value jsonb,reason text NOT NULL,
 outcome text NOT NULL CHECK(outcome IN('succeeded','denied','delivery_failed')),created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE keel_platform_settings(key text PRIMARY KEY CHECK(key='support_email'),value text NOT NULL);
-- Authorizations are auditable approvals only, never a second financial/entitlement grant.
CREATE TABLE keel_platform_approvals(approval_id uuid PRIMARY KEY,kind text NOT NULL CHECK(kind IN('below_floor_price','manual_access','provider_spending')),
 subject text NOT NULL,terms jsonb NOT NULL,expires_at timestamptz NOT NULL,approved_by uuid NOT NULL REFERENCES users(user_id),
 reason text NOT NULL,created_at timestamptz NOT NULL DEFAULT now());
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['keel_platform_workspace','keel_platform_members','keel_platform_invitations','keel_platform_audit','keel_platform_settings','keel_platform_approvals'] LOOP
 EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',t);
 EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',t);
 EXECUTE format('REVOKE ALL ON %I FROM PUBLIC,ceopro_app',t);
 EXECUTE format('CREATE POLICY internal_owner ON %I TO PUBLIC USING(current_user=pg_get_userbyid((SELECT relowner FROM pg_class WHERE oid=%L::regclass))) WITH CHECK(current_user=pg_get_userbyid((SELECT relowner FROM pg_class WHERE oid=%L::regclass)))',t,'public.'||t,'public.'||t);
 END LOOP;
END $$;
CREATE FUNCTION keel_platform_audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Platform audit is append-only' USING ERRCODE='42501'; END $$;
CREATE TRIGGER immutable_audit BEFORE UPDATE OR DELETE ON keel_platform_audit FOR EACH ROW EXECUTE FUNCTION keel_platform_audit_immutable();

CREATE FUNCTION keel_platform_command(action text,p jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE actor uuid:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 role text; result jsonb; old jsonb; target uuid; member keel_platform_members%ROWTYPE;
 inv keel_platform_invitations%ROWTYPE; reason text:=btrim(coalesce(p->>'reason','')); permitted boolean:=false;
BEGIN
 -- Shared serialization prevents owner removal/role races and mutation after suspension.
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_platform_authority',0));
 SELECT m.role_key INTO role FROM keel_platform_members m JOIN users u USING(user_id)
 WHERE m.user_id=actor AND m.status='active' AND u.platform_disabled_at IS NULL;
 permitted:=role IS NOT NULL AND action=ANY(ARRAY['me','overview','companies','company','company_metadata','company_status','users','user','user_status','membership_status','team','invite','invitation_resend','invitation_cancel','audit','settings','settings_update']);
 IF action=ANY(ARRAY['member_update','owner_transfer','financial_approval']) THEN permitted:=role='owner'; END IF;
 IF NOT coalesce(permitted,false) THEN
  INSERT INTO keel_platform_audit(actor_user_id,actor_role,action,subject,reason,outcome)
   VALUES(actor,role,action,coalesce(p->>'id','platform'),'Permission denied','denied');
  RETURN jsonb_build_object('error','forbidden');
 END IF;
 IF action='me' THEN RETURN jsonb_build_object('user_id',actor,'role',role); END IF;
 IF action='overview' THEN
  RETURN jsonb_build_object('companies',(SELECT count(*) FROM companies WHERE deleted_at IS NULL AND tenant_id NOT IN(SELECT tenant_id FROM keel_platform_workspace)),
   'users',(SELECT count(*) FROM users),'active_operators',(SELECT count(*) FROM keel_platform_members WHERE status='active'));
 ELSIF action='companies' THEN
  SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') INTO result FROM (SELECT tenant_id,business_name,country_code,primary_currency,platform_suspended_at,platform_notes FROM companies WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT (p->>'limit')::integer OFFSET (p->>'offset')::integer)x;
 ELSIF action='company' THEN
  SELECT jsonb_build_object('tenant_id',c.tenant_id,'business_name',c.business_name,'country_code',c.country_code,'primary_currency',c.primary_currency,'platform_notes',c.platform_notes,'platform_suspended_at',c.platform_suspended_at,
   'members',(SELECT coalesce(jsonb_agg(jsonb_build_object('user_id',tu.user_id,'role',tu.role_key,'removed_at',tu.removed_at,'tenant_user_id',tu.tenant_user_id,'platform_suspended_at',tu.platform_suspended_at)),'[]') FROM tenant_users tu WHERE tu.tenant_id=c.tenant_id)) INTO result FROM companies c WHERE c.tenant_id=(p->>'id')::uuid AND c.deleted_at IS NULL;
 ELSIF action='users' THEN
  SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') INTO result FROM (SELECT user_id,email,full_name,email_verified_at,platform_disabled_at FROM users ORDER BY created_at DESC LIMIT (p->>'limit')::integer OFFSET (p->>'offset')::integer)x;
 ELSIF action='user' THEN
  SELECT jsonb_build_object('user_id',u.user_id,'email',u.email,'full_name',u.full_name,'platform_disabled_at',u.platform_disabled_at,
   'memberships',(SELECT coalesce(jsonb_agg(jsonb_build_object('tenant_id',tu.tenant_id,'role',tu.role_key,'removed_at',tu.removed_at,'tenant_user_id',tu.tenant_user_id,'platform_suspended_at',tu.platform_suspended_at)),'[]') FROM tenant_users tu WHERE tu.user_id=u.user_id)) INTO result FROM users u WHERE u.user_id=(p->>'id')::uuid;
 ELSIF action='team' THEN
  RETURN jsonb_build_object('members',(SELECT coalesce(jsonb_agg(x),'[]')FROM(
   SELECT m.user_id,u.email,u.full_name,m.role_key AS role,m.status FROM keel_platform_members m JOIN users u USING(user_id)
   ORDER BY m.updated_at DESC,m.user_id LIMIT(p->>'limit')::integer OFFSET(p->>'offset')::integer)x),
   'invitations',(SELECT coalesce(jsonb_agg(x),'[]')FROM(
   SELECT i.invitation_id,i.email,i.expires_at,i.accepted_at,i.canceled_at,CASE WHEN i.expires_at<=clock_timestamp()THEN 'expired'ELSE 'pending'END AS status
   FROM keel_platform_invitations i WHERE i.accepted_at IS NULL AND i.canceled_at IS NULL
   ORDER BY i.created_at DESC,i.invitation_id LIMIT(p->>'limit')::integer OFFSET(p->>'offset')::integer)x));
 ELSIF action='audit' THEN
  SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') INTO result FROM (SELECT * FROM keel_platform_audit ORDER BY created_at DESC LIMIT (p->>'limit')::integer OFFSET (p->>'offset')::integer)x;
 ELSIF action='settings' THEN SELECT coalesce(jsonb_object_agg(key,value),'{}') INTO result FROM keel_platform_settings;
 ELSE
  IF length(reason)<1 OR length(reason)>2000 THEN RETURN jsonb_build_object('error','reason_required'); END IF;
  IF action IN('company_metadata','company_status') THEN
   target:=(p->>'id')::uuid;
   PERFORM pg_advisory_xact_lock(hashtextextended('keel_billing_tenant:'||target::text,0));
   SELECT to_jsonb(c) INTO old FROM companies c WHERE tenant_id=target AND deleted_at IS NULL FOR UPDATE;
   IF old IS NULL THEN RETURN jsonb_build_object('error','not_found'); END IF;
   IF EXISTS(SELECT 1 FROM keel_platform_workspace WHERE tenant_id=target) THEN RETURN jsonb_build_object('error','protected'); END IF;
   IF action='company_metadata' THEN UPDATE companies SET platform_notes=p->>'notes' WHERE tenant_id=target;
   ELSE UPDATE companies SET platform_suspended_at=CASE WHEN (p->>'active')::boolean THEN NULL ELSE now() END WHERE tenant_id=target; END IF;
   SELECT jsonb_build_object('tenant_id',tenant_id,'notes',platform_notes,'suspended_at',platform_suspended_at) INTO result FROM companies WHERE tenant_id=target;
   old:=jsonb_build_object('notes',old->'platform_notes','suspended_at',old->'platform_suspended_at');
  ELSIF action='membership_status' THEN
   target:=(p->>'id')::uuid;
   SELECT jsonb_build_object('tenant_id',tu.tenant_id,'user_id',tu.user_id,'role_key',tu.role_key,'removed_at',tu.removed_at,'platform_suspended_at',tu.platform_suspended_at) INTO old FROM tenant_users tu WHERE tenant_user_id=target;
   IF old IS NULL THEN RETURN jsonb_build_object('error','not_found'); END IF;
   IF EXISTS(SELECT 1 FROM keel_platform_workspace WHERE tenant_id=(old->>'tenant_id')::uuid) THEN RETURN jsonb_build_object('error','protected'); END IF;
   PERFORM pg_advisory_xact_lock(hashtextextended('keel_billing_tenant:'||(old->>'tenant_id'),0));
   PERFORM pg_advisory_xact_lock(hashtextextended('keel_capacity:'||(old->>'tenant_id')||':team_seats',0));
   SELECT jsonb_build_object('tenant_id',tu.tenant_id,'user_id',tu.user_id,'role_key',tu.role_key,'removed_at',tu.removed_at,'platform_suspended_at',tu.platform_suspended_at) INTO old FROM tenant_users tu WHERE tenant_user_id=target FOR UPDATE;
   IF NOT (p->>'active')::boolean AND old->>'role_key'='owner' AND old->>'removed_at' IS NULL AND NOT EXISTS(SELECT 1 FROM tenant_users tu JOIN users u USING(user_id) WHERE tu.tenant_id=(old->>'tenant_id')::uuid AND tu.tenant_user_id<>target AND tu.role_key='owner' AND tu.removed_at IS NULL AND tu.platform_suspended_at IS NULL AND u.platform_disabled_at IS NULL) THEN RETURN jsonb_build_object('error','last_owner'); END IF;
   IF (p->>'active')::boolean THEN
    IF old->>'platform_suspended_at' IS NULL OR old->>'platform_suspended_at' IS DISTINCT FROM old->>'removed_at' THEN RETURN jsonb_build_object('error','protected'); END IF;
    UPDATE tenant_users SET platform_suspended_at=NULL,removed_at=NULL WHERE tenant_user_id=target;
   ELSE
    IF old->>'removed_at' IS NOT NULL THEN RETURN jsonb_build_object('error','protected'); END IF;
    UPDATE tenant_users SET platform_suspended_at=now(),removed_at=now() WHERE tenant_user_id=target;
   END IF;
   result:=jsonb_build_object('tenant_user_id',target,'active',(p->>'active')::boolean);
  ELSIF action='user_status' THEN
   target:=(p->>'id')::uuid;
   IF EXISTS(SELECT 1 FROM keel_platform_members WHERE user_id=target) AND (role<>'owner' OR EXISTS(SELECT 1 FROM keel_platform_members WHERE user_id=target AND role_key='owner')) THEN RETURN jsonb_build_object('error','protected'); END IF;
   -- Status changes share the Task 6 commercial lock as well as team-seat locks.
   PERFORM pg_advisory_xact_lock(hashtextextended('keel_billing_tenant:'||tu.tenant_id::text,0)) FROM tenant_users tu WHERE tu.user_id=target ORDER BY tu.tenant_id;
   PERFORM pg_advisory_xact_lock(hashtextextended('keel_capacity:'||tu.tenant_id::text||':team_seats',0)) FROM tenant_users tu WHERE tu.user_id=target ORDER BY tu.tenant_id;
   IF NOT (p->>'active')::boolean AND EXISTS(SELECT 1 FROM tenant_users tu WHERE tu.user_id=target AND tu.role_key='owner' AND tu.removed_at IS NULL
    AND NOT EXISTS(SELECT 1 FROM tenant_users other JOIN users u ON u.user_id=other.user_id WHERE other.tenant_id=tu.tenant_id AND other.user_id<>target AND other.role_key='owner' AND other.removed_at IS NULL AND u.platform_disabled_at IS NULL)) THEN RETURN jsonb_build_object('error','last_owner'); END IF;
   SELECT jsonb_build_object('disabled_at',platform_disabled_at) INTO old FROM users WHERE user_id=target FOR UPDATE;
   IF old IS NULL THEN RETURN jsonb_build_object('error','not_found'); END IF;
   UPDATE users SET platform_disabled_at=CASE WHEN (p->>'active')::boolean THEN NULL ELSE now() END WHERE user_id=target;
   result:=jsonb_build_object('user_id',target,'active',(p->>'active')::boolean);
  ELSIF action='invite' THEN
   IF EXISTS(SELECT 1 FROM keel_platform_members m JOIN users u USING(user_id) WHERE lower(u.email)=lower(p->>'email') AND m.status='active') THEN RETURN jsonb_build_object('error','already_member'); END IF;
   UPDATE keel_platform_invitations SET canceled_at=now() WHERE lower(email)=lower(p->>'email') AND accepted_at IS NULL AND canceled_at IS NULL;
   INSERT INTO keel_platform_invitations(email,token_hash,expires_at,created_by) VALUES(lower(p->>'email'),p->>'token_hash',(p->>'expires_at')::timestamptz,actor) RETURNING jsonb_build_object('invitation_id',invitation_id,'email',email,'expires_at',expires_at) INTO result;
  ELSIF action IN('invitation_resend','invitation_cancel') THEN
   SELECT * INTO inv FROM keel_platform_invitations WHERE invitation_id=(p->>'id')::uuid FOR UPDATE;
   IF inv.invitation_id IS NULL OR inv.accepted_at IS NOT NULL OR inv.canceled_at IS NOT NULL THEN RETURN jsonb_build_object('error','not_found'); END IF;
   IF action='invitation_cancel' THEN UPDATE keel_platform_invitations SET canceled_at=now() WHERE invitation_id=inv.invitation_id;
   ELSE UPDATE keel_platform_invitations SET token_hash=p->>'token_hash',expires_at=(p->>'expires_at')::timestamptz,created_by=actor WHERE invitation_id=inv.invitation_id; END IF;
   result:=jsonb_build_object('invitation_id',inv.invitation_id,'email',inv.email);
  ELSIF action='member_update' THEN
   target:=(p->>'id')::uuid;
   SELECT * INTO member FROM keel_platform_members WHERE user_id=target FOR UPDATE;
   IF member.user_id IS NULL THEN RETURN jsonb_build_object('error','not_found'); END IF;
   IF member.role_key='owner' THEN RETURN jsonb_build_object('error','last_owner'); END IF;
   IF p->>'status' NOT IN('active','suspended','removed') THEN RETURN jsonb_build_object('error','invalid'); END IF;
   old:=to_jsonb(member);
   UPDATE keel_platform_members SET status=p->>'status',updated_at=now() WHERE user_id=target;
   result:=jsonb_build_object('user_id',target,'role','admin','status',p->>'status');
  ELSIF action='owner_transfer' THEN
   target:=(p->>'id')::uuid;
   IF target=actor OR NOT EXISTS(SELECT 1 FROM keel_platform_members m JOIN users u USING(user_id) WHERE m.user_id=target AND m.status='active' AND m.role_key='admin' AND u.platform_disabled_at IS NULL) THEN RETURN jsonb_build_object('error','invalid'); END IF;
   UPDATE keel_platform_members SET role_key='admin',updated_at=now() WHERE user_id=actor;
   UPDATE keel_platform_members SET role_key='owner',updated_at=now() WHERE user_id=target;
   UPDATE tenant_users SET role_key='staff' WHERE user_id=actor AND tenant_id IN(SELECT tenant_id FROM keel_platform_workspace);
   UPDATE tenant_users SET role_key='owner' WHERE user_id=target AND tenant_id IN(SELECT tenant_id FROM keel_platform_workspace);
   result:=jsonb_build_object('previous_owner',actor,'owner',target);
  ELSIF action='settings_update' THEN
   INSERT INTO keel_platform_settings VALUES('support_email',p->>'support_email') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value;
   result:=jsonb_build_object('support_email',p->>'support_email');
  ELSIF action='financial_approval' THEN
   IF (p->>'expires_at')::timestamptz<=now() THEN RETURN jsonb_build_object('error','invalid'); END IF;
   INSERT INTO keel_platform_approvals(approval_id,kind,subject,terms,expires_at,approved_by,reason)
   VALUES((p->>'request_id')::uuid,p->>'kind',p->>'subject',p->'terms',(p->>'expires_at')::timestamptz,actor,reason) ON CONFLICT(approval_id) DO NOTHING;
   SELECT to_jsonb(a) INTO result FROM keel_platform_approvals a WHERE approval_id=(p->>'request_id')::uuid;
   IF result->>'approved_by'<>actor::text OR result->>'kind'<>p->>'kind' OR result->>'subject'<>p->>'subject' OR result->>'reason'<>reason OR result->'terms' IS DISTINCT FROM p->'terms' OR (result->>'expires_at')::timestamptz<>(p->>'expires_at')::timestamptz THEN RETURN jsonb_build_object('error','idempotency_conflict'); END IF;
  ELSE RETURN jsonb_build_object('error','invalid'); END IF;
  INSERT INTO keel_platform_audit(actor_user_id,actor_role,action,subject,old_value,new_value,reason,outcome)
   VALUES(actor,role,action,coalesce(p->>'id',p->>'subject','platform'),old,result,reason,'succeeded');
 END IF;
 IF result IS NULL THEN RETURN jsonb_build_object('error','not_found'); END IF;
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION keel_platform_command(text,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION keel_platform_command(text,jsonb) TO ceopro_app;

CREATE FUNCTION keel_platform_accept(token_digest text, p jsonb, consume boolean) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE inv keel_platform_invitations%ROWTYPE;uid uuid;tid uuid;display_name text;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_platform_authority',0));
 SELECT * INTO inv FROM keel_platform_invitations WHERE token_hash=token_digest FOR UPDATE;
 IF inv.invitation_id IS NULL OR inv.accepted_at IS NOT NULL OR inv.canceled_at IS NOT NULL OR inv.expires_at<=clock_timestamp()
 OR NOT EXISTS(SELECT 1 FROM keel_platform_members m JOIN users u USING(user_id) WHERE m.user_id=inv.created_by AND m.status='active' AND u.platform_disabled_at IS NULL) THEN RETURN jsonb_build_object('error','not_found'); END IF;
 IF NOT consume THEN RETURN jsonb_build_object('email',inv.email,'role','admin','expires_at',inv.expires_at); END IF;
 SELECT tenant_id INTO tid FROM keel_platform_workspace;
 IF tid IS NULL THEN RETURN jsonb_build_object('error','not_configured'); END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_signup:'||lower(inv.email),0));
 SELECT user_id,full_name INTO uid,display_name FROM users WHERE lower(email)=lower(inv.email) AND platform_disabled_at IS NULL FOR UPDATE;
 IF uid IS NULL THEN
   IF EXISTS(SELECT 1 FROM users WHERE lower(email)=lower(inv.email)) THEN RETURN jsonb_build_object('error','forbidden'); END IF;
   IF nullif(btrim(p->>'full_name'),'') IS NULL OR nullif(p->>'password_hash','') IS NULL THEN RETURN jsonb_build_object('error','new_credentials_required'); END IF;
   uid:=gen_random_uuid();display_name:=p->>'full_name';
   INSERT INTO users(user_id,email,password_hash,full_name,email_verified_at) VALUES(uid,inv.email,p->>'password_hash',display_name,now());
 END IF;
 -- Existing active members cannot be downgraded/replaced by an old invitation.
 IF EXISTS(SELECT 1 FROM keel_platform_members WHERE user_id=uid AND status='active') THEN RETURN jsonb_build_object('error','already_member'); END IF;
 UPDATE users SET email_verified_at=coalesce(email_verified_at,now()) WHERE user_id=uid;
 INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(tid,uid,'staff')
  ON CONFLICT(tenant_id,user_id) DO UPDATE SET removed_at=NULL;
 INSERT INTO keel_platform_members(user_id,role_key,status) VALUES(uid,'admin','active')
  ON CONFLICT(user_id) DO UPDATE SET role_key='admin',status='active',updated_at=now();
 UPDATE keel_platform_invitations SET accepted_at=now(),accepted_by=uid WHERE invitation_id=inv.invitation_id;
 INSERT INTO keel_platform_audit(actor_user_id,actor_role,action,subject,new_value,reason,outcome)
 VALUES(uid,'admin','invitation_accept',inv.invitation_id::text,jsonb_build_object('invited_by',inv.created_by),'Verified invitation possession','succeeded');
 RETURN jsonb_build_object('user_id',uid,'tenant_id',tid,'email',inv.email,'full_name',display_name,'business_name','KEEL Platform','role_key','staff');
END $$;
REVOKE ALL ON FUNCTION keel_platform_accept(text,jsonb,boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION keel_platform_accept(text,jsonb,boolean) TO ceopro_app;

CREATE FUNCTION keel_platform_record_attempt(action text,subject text,reason text,outcome text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE actor uuid:=nullif(current_setting('app.current_user_id',true),'')::uuid;role text;
BEGIN
 SELECT role_key INTO role FROM keel_platform_members WHERE user_id=actor AND status='active';
 INSERT INTO keel_platform_audit(actor_user_id,actor_role,action,subject,reason,outcome)
 VALUES(actor,role,left(action,100),left(subject,255),left(reason,2000),outcome);
END $$;
REVOKE ALL ON FUNCTION keel_platform_record_attempt(text,text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION keel_platform_record_attempt(text,text,text,text) TO ceopro_app;

-- Bootstrap is intentionally not executable by ceopro_app or through HTTP.
CREATE FUNCTION keel_bootstrap_platform_owner(uid uuid,country text,currency text,reason text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE tid uuid;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_platform_authority',0));
 IF EXISTS(SELECT 1 FROM keel_platform_workspace) THEN RAISE EXCEPTION 'Platform already bootstrapped'; END IF;
 IF NOT EXISTS(SELECT 1 FROM users WHERE user_id=uid AND email_verified_at IS NOT NULL AND platform_disabled_at IS NULL) THEN RAISE EXCEPTION 'An existing verified active user is required'; END IF;
 IF nullif(btrim(reason),'') IS NULL THEN RAISE EXCEPTION 'Reason required'; END IF;
 tid:=gen_random_uuid();
 INSERT INTO companies(tenant_id,business_name,country_code,primary_currency,supported_currencies)
 VALUES(tid,'KEEL Platform',country,currency,ARRAY[currency]);
 INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(tid,uid,'owner');
 INSERT INTO keel_platform_workspace VALUES(true,tid);
 INSERT INTO keel_platform_members(user_id,role_key) VALUES(uid,'owner');
 INSERT INTO keel_platform_audit(actor_user_id,actor_role,action,subject,reason,outcome)
 VALUES(uid,'owner','bootstrap',tid::text,reason,'succeeded');
 RETURN tid;
END $$;
REVOKE ALL ON FUNCTION keel_bootstrap_platform_owner(uuid,text,text,text) FROM PUBLIC,ceopro_app;

CREATE OR REPLACE FUNCTION keel_active_principal(uid uuid,tid uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT uid<>'00000000-0000-0000-0000-000000000000'::uuid AND EXISTS(
 SELECT 1 FROM users u JOIN tenant_users tu ON tu.user_id=u.user_id JOIN companies c ON c.tenant_id=tu.tenant_id
 WHERE u.user_id=uid AND c.tenant_id=tid AND u.platform_disabled_at IS NULL AND c.platform_suspended_at IS NULL
 AND c.deleted_at IS NULL AND tu.removed_at IS NULL AND tu.platform_suspended_at IS NULL)
 AND (NOT EXISTS(SELECT 1 FROM keel_platform_workspace WHERE tenant_id=tid)
 OR EXISTS(SELECT 1 FROM keel_platform_members WHERE user_id=uid AND status='active'));
$$;

CREATE FUNCTION keel_accept_team_invitation(digest text,display_name text,password text,seat_limit bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE inv auth_tokens%ROWTYPE;u users%ROWTYPE;uid uuid;biz text;
BEGIN
 SELECT * INTO inv FROM auth_tokens WHERE token_type='TEAM_INVITATION' AND token_hash=digest AND used_at IS NULL AND expires_at>now() FOR UPDATE;
 IF inv.token_id IS NULL OR EXISTS(SELECT 1 FROM keel_platform_workspace WHERE tenant_id=inv.tenant_id) THEN RETURN jsonb_build_object('error','invalid'); END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_signup:'||lower(inv.email),0));
 SELECT * INTO u FROM users WHERE lower(email)=lower(inv.email) FOR UPDATE;
 IF u.user_id IS NULL THEN
  IF nullif(btrim(display_name),'') IS NULL OR password IS NULL THEN RETURN jsonb_build_object('error','credentials_required'); END IF;
  uid:=gen_random_uuid();
  INSERT INTO users(user_id,email,password_hash,full_name,email_verified_at) VALUES(uid,inv.email,password,display_name,now());
 ELSE
  IF u.platform_disabled_at IS NOT NULL THEN RETURN jsonb_build_object('error','invalid'); END IF;
  uid:=u.user_id;display_name:=u.full_name;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM companies WHERE tenant_id=inv.tenant_id AND platform_suspended_at IS NULL AND deleted_at IS NULL) THEN RAISE EXCEPTION 'inactive_company'; END IF;
 IF EXISTS(SELECT 1 FROM tenant_users WHERE tenant_id=inv.tenant_id AND user_id=uid AND platform_suspended_at IS NOT NULL) THEN RAISE EXCEPTION 'platform_suspended_membership'; END IF;
 IF NOT auth_join_tenant(inv.tenant_id,uid,inv.role_key,seat_limit) THEN RAISE EXCEPTION 'seat_capacity'; END IF;
 UPDATE users SET email_verified_at=coalesce(email_verified_at,now()) WHERE user_id=uid;
 UPDATE auth_tokens SET used_at=now() WHERE token_id=inv.token_id;
 SELECT business_name INTO biz FROM companies WHERE tenant_id=inv.tenant_id;
 RETURN jsonb_build_object('user_id',uid,'email',inv.email,'full_name',display_name,'business_name',biz,'role_key',inv.role_key,'preferred_language',coalesce(u.preferred_language,'en'));
END $$;
REVOKE ALL ON FUNCTION keel_accept_team_invitation(text,text,text,bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION keel_accept_team_invitation(text,text,text,bigint) TO ceopro_app;

CREATE TRIGGER immutable_audit_truncate BEFORE TRUNCATE ON keel_platform_audit FOR EACH STATEMENT EXECUTE FUNCTION keel_platform_audit_immutable();

-- Inactive platform membership cannot remain a selectable workspace at login/refresh.
CREATE OR REPLACE FUNCTION auth_lookup_user_memberships(p_user_id uuid)
RETURNS TABLE(tenant_id uuid,role_key varchar,business_name varchar)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT tu.tenant_id,tu.role_key,c.business_name FROM tenant_users tu JOIN companies c USING(tenant_id)
 JOIN users u ON u.user_id=tu.user_id WHERE tu.user_id=p_user_id AND tu.removed_at IS NULL
 AND tu.platform_suspended_at IS NULL AND c.platform_suspended_at IS NULL AND c.deleted_at IS NULL
 AND u.platform_disabled_at IS NULL AND (NOT EXISTS(SELECT 1 FROM keel_platform_workspace w WHERE w.tenant_id=tu.tenant_id)
 OR EXISTS(SELECT 1 FROM keel_platform_members m WHERE m.user_id=tu.user_id AND m.status='active'))
 ORDER BY tu.joined_at;
$$;

-- Durable revocations extend the existing Python identity. Redis can deny from cache,
-- but an empty/restarted cache never authorizes a token revoked in the database.
CREATE TABLE keel_revoked_tokens(token_hash char(64) PRIMARY KEY,expires_at timestamptz NOT NULL,revoked_at timestamptz NOT NULL DEFAULT now());
ALTER TABLE keel_revoked_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE keel_revoked_tokens FORCE ROW LEVEL SECURITY;
REVOKE ALL ON keel_revoked_tokens FROM PUBLIC,ceopro_app;
CREATE POLICY internal_owner ON keel_revoked_tokens TO PUBLIC
 USING(current_user=pg_get_userbyid((SELECT relowner FROM pg_class WHERE oid='public.keel_revoked_tokens'::regclass)))
 WITH CHECK(current_user=pg_get_userbyid((SELECT relowner FROM pg_class WHERE oid='public.keel_revoked_tokens'::regclass)));
CREATE FUNCTION keel_token_revocation(action text,digest text,expiry timestamptz)RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
BEGIN
 IF action='record' THEN
  IF expiry IS NULL THEN RAISE EXCEPTION 'Revocation expiry required';END IF;
  INSERT INTO keel_revoked_tokens(token_hash,expires_at)VALUES(digest,expiry)
   ON CONFLICT(token_hash)DO UPDATE SET expires_at=greatest(keel_revoked_tokens.expires_at,EXCLUDED.expires_at);
  RETURN true;
 ELSIF action='check' THEN
  RETURN EXISTS(SELECT 1 FROM keel_revoked_tokens WHERE token_hash=digest AND expires_at>now());
 END IF;
 RAISE EXCEPTION 'Invalid revocation operation';
END $$;
REVOKE ALL ON FUNCTION keel_token_revocation(text,text,timestamptz)FROM PUBLIC;
GRANT EXECUTE ON FUNCTION keel_token_revocation(text,text,timestamptz)TO ceopro_app;

-- Six-digit codes are scoped by user/type. Global historical hash uniqueness
-- caused collisions across unrelated users; preserve token rows and the latest live code.
ALTER TABLE auth_tokens ADD COLUMN failed_attempts integer NOT NULL DEFAULT 0 CHECK(failed_attempts>=0);
WITH ranked AS (
 SELECT token_id,row_number()OVER(PARTITION BY user_id,token_type ORDER BY created_at DESC,token_id DESC) n
 FROM auth_tokens WHERE used_at IS NULL AND token_type IN('PASSWORD_RESET','EMAIL_VERIFICATION')
) UPDATE auth_tokens t SET used_at=now() FROM ranked r WHERE t.token_id=r.token_id AND r.n>1;
DROP INDEX IF EXISTS uq_auth_tokens_hash;
CREATE UNIQUE INDEX uq_auth_tokens_invitation_hash ON auth_tokens(token_hash) WHERE token_type='TEAM_INVITATION';
CREATE UNIQUE INDEX uq_auth_tokens_live_account_code ON auth_tokens(user_id,token_type) WHERE used_at IS NULL AND token_type IN('PASSWORD_RESET','EMAIL_VERIFICATION');
CREATE INDEX idx_auth_tokens_send_window ON auth_tokens(user_id,created_at);

CREATE FUNCTION keel_is_platform_workspace(tid uuid)RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT EXISTS(SELECT 1 FROM keel_platform_workspace WHERE tenant_id=tid);
$$;
REVOKE ALL ON FUNCTION keel_is_platform_workspace(uuid)FROM PUBLIC;
GRANT EXECUTE ON FUNCTION keel_is_platform_workspace(uuid)TO ceopro_app;

-- Existing tokens without cv are version zero. No existing account is forcibly logged out.
ALTER TABLE users ADD COLUMN credential_version bigint NOT NULL DEFAULT 0 CHECK(credential_version>=0);
CREATE FUNCTION auth_credential_version(uid uuid)RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT credential_version FROM users WHERE user_id=uid;
$$;
REVOKE ALL ON FUNCTION auth_credential_version(uuid)FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_credential_version(uuid)TO ceopro_app;
CREATE OR REPLACE FUNCTION auth_reset_password(p_user_id uuid,p_new_password_hash text)RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
 UPDATE users SET password_hash=p_new_password_hash,credential_version=credential_version+1,updated_at=now()WHERE user_id=p_user_id;
$$;
REVOKE ALL ON FUNCTION auth_reset_password(uuid,text)FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth_reset_password(uuid,text)TO ceopro_app;
