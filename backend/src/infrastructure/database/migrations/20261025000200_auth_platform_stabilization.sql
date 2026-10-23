-- Phase1A stabilization: forward-only correction; preserves existing identities and histories.
CREATE OR REPLACE FUNCTION keel_platform_command(action text,p jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE actor uuid:=nullif(current_setting('app.current_user_id',true),'')::uuid;
 role text; result jsonb; old jsonb; target uuid; member keel_platform_members%ROWTYPE;
 inv keel_platform_invitations%ROWTYPE; reason text:=btrim(coalesce(p->>'reason','')); permitted boolean:=false;
BEGIN
 -- Shared serialization prevents owner removal/role races and mutation after suspension.
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_platform_authority',0));
 SELECT m.role_key INTO role FROM keel_platform_members m JOIN users u USING(user_id)
 WHERE m.user_id=actor AND m.status='active' AND u.platform_disabled_at IS NULL;
 permitted:=role IS NOT NULL AND action=ANY(ARRAY['me','overview','companies','company','company_metadata','company_status','users','user','user_status','membership_status','membership_restore_scope','team','invite','invitation_resend','invitation_cancel','audit','settings','settings_update']);
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
 ELSIF action='membership_restore_scope' THEN
  SELECT tu.tenant_id INTO target FROM tenant_users tu WHERE tu.tenant_user_id=(p->>'id')::uuid;
  IF target IS NULL THEN RETURN jsonb_build_object('error','not_found'); END IF;
  IF EXISTS(SELECT 1 FROM keel_platform_workspace WHERE tenant_id=target) THEN RETURN jsonb_build_object('error','protected'); END IF;
  PERFORM pg_advisory_xact_lock(hashtextextended('keel_billing_tenant:'||target::text,0));
  PERFORM pg_advisory_xact_lock(hashtextextended('keel_capacity:'||target::text||':team_seats',0));
  RETURN jsonb_build_object('tenant_id',target);
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
    IF NOT (p ? '_seat_limit') THEN RETURN jsonb_build_object('error','seat_capacity'); END IF;
    -- Reuse the existing canonical seat-count/join operation, under the original locks.
    IF NOT auth_join_tenant((old->>'tenant_id')::uuid,(old->>'user_id')::uuid,(old->>'role_key')::varchar,(p->>'_seat_limit')::bigint) THEN
     RETURN jsonb_build_object('error','seat_capacity');
    END IF;
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
   IF EXISTS(SELECT 1 FROM keel_platform_members m JOIN users u USING(user_id) WHERE lower(u.email)=lower(p->>'email') AND m.status<>'active') THEN RETURN jsonb_build_object('error','operator_inactive'); END IF;
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

CREATE OR REPLACE FUNCTION keel_platform_accept(token_digest text, p jsonb, consume boolean) RETURNS jsonb
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
 IF inv.expires_at<=clock_timestamp() THEN RETURN jsonb_build_object('error','not_found'); END IF;
 SELECT user_id,full_name INTO uid,display_name FROM users WHERE lower(email)=lower(inv.email) AND platform_disabled_at IS NULL FOR UPDATE;
 IF uid IS NULL THEN
   IF EXISTS(SELECT 1 FROM users WHERE lower(email)=lower(inv.email)) THEN RETURN jsonb_build_object('error','forbidden'); END IF;
   IF nullif(btrim(p->>'full_name'),'') IS NULL OR nullif(p->>'password_hash','') IS NULL THEN RETURN jsonb_build_object('error','new_credentials_required'); END IF;
   uid:=gen_random_uuid();display_name:=p->>'full_name';
   INSERT INTO users(user_id,email,password_hash,full_name,email_verified_at) VALUES(uid,inv.email,p->>'password_hash',display_name,now());
 END IF;
 IF EXISTS(SELECT 1 FROM keel_platform_members WHERE user_id=uid AND status<>'active') THEN RETURN jsonb_build_object('error','operator_inactive'); END IF;
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


-- Revalidate invitation deadlines after lock waits using wall-clock time.
CREATE OR REPLACE FUNCTION keel_accept_team_invitation(digest text,display_name text,password text,seat_limit bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE inv auth_tokens%ROWTYPE;u users%ROWTYPE;uid uuid;biz text;
BEGIN
 SELECT * INTO inv FROM auth_tokens WHERE token_type='TEAM_INVITATION' AND token_hash=digest AND used_at IS NULL AND expires_at>clock_timestamp() FOR UPDATE;
 IF inv.token_id IS NULL OR inv.expires_at<=clock_timestamp() OR EXISTS(SELECT 1 FROM keel_platform_workspace WHERE tenant_id=inv.tenant_id) THEN RETURN jsonb_build_object('error','invalid'); END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('keel_signup:'||lower(inv.email),0));
 IF inv.expires_at<=clock_timestamp() THEN RETURN jsonb_build_object('error','invalid'); END IF;
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
