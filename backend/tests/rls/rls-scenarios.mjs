import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';

// All fixtures and writes are rolled back. Authorization assertions execute as
// ceopro_app, never as the fixture-creating migration identity.
export async function runRlsScenarios(db) {
  let checks = 0;
  const q = (sql, values = []) => db.query(sql, values);
  const one = async (sql, values = []) => (await q(sql, values)).rows[0];
  const context = async (user = '', tenant = '', email = '') => q(
    `SELECT set_config('app.current_user_id',$1,true),
      set_config('app.current_tenant_id',$2,true), set_config('app.auth_email',$3,true)`,
    [user, tenant, email]);
  const check = async (name, action) => { await action(); checks++; console.log(`PASS ${name}`); };
  const rejects = async (action, code) => {
    await q('SAVEPOINT expected_error');
    try { await assert.rejects(action, error => error.code === code); }
    finally { await q('ROLLBACK TO SAVEPOINT expected_error'); await q('RELEASE SAVEPOINT expected_error'); }
  };
  const id = Object.fromEntries(['a','b','platform','deleted','owner','admin','staff','other','po','pa','ps','removed','suspended','deletedMember','newUser','newTenant','session'].map(k => [k,randomUUID()]));
  const email = `${id.owner}@rls-regression.example`;
  const targetUsers = [id.owner,id.admin,id.staff,id.other,id.po,id.pa,id.ps,id.removed,id.suspended,id.deletedMember];
  await q('BEGIN');
  try {
    await q(`INSERT INTO public.companies(tenant_id,business_name,business_type,country_code,primary_currency,deleted_at)
      VALUES ($1,'RLS A','retail','JO','USD',NULL), ($2,'RLS B','retail','JO','USD',NULL),
      ($3,'RLS platform','platform','JO','USD',NULL),($4,'RLS deleted','retail','JO','USD',now())`,[id.a,id.b,id.platform,id.deleted]);
    for (const user of targetUsers) await q(`INSERT INTO public.users(user_id,email,password_hash)
      VALUES ($1,$2,'not-a-login-password')`,[user,user===id.owner?email:`${user}@rls-regression.example`]);
    for (const [user,tenant,role,removed,status] of [
      [id.owner,id.a,'owner',false,'active'],[id.admin,id.a,'admin',false,'active'],[id.staff,id.a,'staff',false,'active'],
      [id.other,id.b,'owner',false,'active'],[id.po,id.platform,'owner',false,'active'],[id.pa,id.platform,'admin',false,'active'],
      [id.ps,id.platform,'staff',false,'active'],[id.removed,id.platform,'admin',true,'active'],
      [id.suspended,id.platform,'admin',false,'suspended'],[id.deletedMember,id.deleted,'owner',false,'active']
    ]) await q(`INSERT INTO public.tenant_users(tenant_id,user_id,role_key,removed_at,platform_status)
      VALUES($1,$2,$3,CASE WHEN $4 THEN now() ELSE NULL END,$5)`,[tenant,user,role,removed,status]);
    await q('SET LOCAL ROLE ceopro_app');
    await check('restricted runtime identity and FORCE RLS',async()=>{
      const role=await one(`SELECT current_user AS name, rolsuper, rolbypassrls FROM pg_catalog.pg_roles WHERE rolname=current_user`);
      assert.equal(role.name,'ceopro_app');assert.equal(role.rolsuper,false);assert.equal(role.rolbypassrls,false);
      const flags=(await q(`SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_catalog.pg_class
        WHERE oid IN ('public.users'::regclass,'public.tenant_users'::regclass,'public.companies'::regclass)`)).rows;
      assert.equal(flags.length,3);for(const f of flags){assert.equal(f.relrowsecurity,true);assert.equal(f.relforcerowsecurity,true);}
    });
    await check('new signup email lookup returns no row',async()=>{
      await context('','',`${id.newUser}@rls-regression.example`);
      assert.equal((await q(`SELECT * FROM public.users WHERE lower(email)=lower($1)`,[`${id.newUser}@rls-regression.example`])).rows.length,0);
    });
    await check('existing signup email and case-insensitive login lookup',async()=>{
      await context('','',email.toUpperCase());
      assert.equal((await one(`SELECT user_id FROM public.users WHERE lower(email)=lower($1)`,[email])).user_id,id.owner);
      assert.equal((await q(`SELECT user_id FROM public.users WHERE user_id=$1`,[id.other])).rows.length,0);
    });
    await check('login membership function with valid email',async()=>{
      await context(id.owner,'',email);
      assert.deepEqual((await q('SELECT tenant_id FROM public.auth_login_memberships($1)',[id.owner])).rows.map(r=>r.tenant_id),[id.a]);
      assert.equal((await q('SELECT * FROM public.auth_login_memberships($1)',[id.other])).rows.length,0);
      await context(id.owner,'','wrong@rls-regression.example');
      assert.equal((await q('SELECT * FROM public.auth_login_memberships($1)',[id.owner])).rows.length,0);
    });
    await check('signup INSERT RETURNING user, company and first membership',async()=>{
      await context(id.newUser,id.newTenant,`${id.newUser}@rls-regression.example`);
      assert.equal((await one(`INSERT INTO public.users(user_id,email,password_hash) VALUES($1,$2,'test-only') RETURNING user_id`,[id.newUser,`${id.newUser}@rls-regression.example`])).user_id,id.newUser);
      assert.equal((await one(`INSERT INTO public.companies(tenant_id,business_name,country_code,primary_currency)
        VALUES($1,'RLS signup','JO','USD') RETURNING tenant_id`,[id.newTenant])).tenant_id,id.newTenant);
      assert.equal((await one(`INSERT INTO public.tenant_users(tenant_id,user_id,role_key) VALUES($1,$2,'owner') RETURNING tenant_id`,[id.newTenant,id.newUser])).tenant_id,id.newTenant);
      await rejects(()=>q(`INSERT INTO public.users(email,password_hash) VALUES($1,'duplicate')`,[email.toUpperCase()]),'23505');
    });
    await check('session create, refresh and logout persistence',async()=>{
      await context(id.owner,id.a);
      await q(`INSERT INTO public.auth_sessions(id,user_id,tenant_id,device,expires_at) VALUES($1,$2,$3,'RLS regression',now()+interval '1 hour')`,[id.session,id.owner,id.a]);
      assert.equal((await one(`UPDATE public.auth_sessions SET expires_at=now()+interval '2 hours' WHERE id=$1 RETURNING id`,[id.session])).id,id.session);
      await q(`UPDATE public.auth_sessions SET revoked_at=now() WHERE id=$1`,[id.session]);
      assert.equal((await q(`SELECT id FROM public.auth_sessions WHERE id=$1 AND revoked_at IS NULL`,[id.session])).rows.length,0);
    });
    await check('tenant owner/admin reads own users and memberships',async()=>{
      for(const user of [id.owner,id.admin]){
        await context(user,id.a);
        assert.deepEqual((await q(`SELECT user_id FROM public.users WHERE user_id=ANY($1::uuid[]) ORDER BY user_id`,[[id.owner,id.admin,id.staff]])).rows.map(r=>r.user_id).sort(),[id.owner,id.admin,id.staff].sort());
        assert.equal((await q(`SELECT * FROM public.tenant_users WHERE tenant_id=$1`,[id.a])).rows.length,3);
      }
    });
    await check('standard tenant cannot read another tenant or platform directory',async()=>{
      await context(id.staff,id.a);
      assert.equal((await q(`SELECT * FROM public.users WHERE user_id=$1`,[id.other])).rows.length,0);
      assert.equal((await q(`SELECT * FROM public.tenant_users WHERE tenant_id=$1`,[id.b])).rows.length,0);
      assert.equal((await q(`SELECT * FROM public.companies WHERE tenant_id=$1`,[id.b])).rows.length,0);
      assert.equal((await one('SELECT public.is_verified_platform_admin_context() AS allowed')).allowed,false);
      assert.equal((await one('SELECT public.platform_admin_can_read_customer_user($1) AS allowed',[id.other])).allowed,false);
      assert.equal((await one('SELECT public.platform_admin_can_read_customer_tenant($1) AS allowed',[id.b])).allowed,false);
    });
    await check('platform owner/admin customer list reads and overview',async()=>{
      for(const user of [id.po,id.pa]){
        await context(user,id.platform);
        assert.equal((await one('SELECT public.is_verified_platform_admin_context() AS allowed')).allowed,true);
        assert.equal((await q(`SELECT * FROM public.users WHERE user_id=$1`,[id.other])).rows.length,1);
        assert.equal((await q(`SELECT * FROM public.tenant_users WHERE tenant_id=$1`,[id.b])).rows.length,1);
        assert.equal((await q(`SELECT * FROM public.companies WHERE tenant_id=$1`,[id.b])).rows.length,1);
        assert.equal((await q(`SELECT * FROM public.companies WHERE tenant_id=$1`,[id.deleted])).rows.length,0);
        assert.equal((await q(`SELECT * FROM public.users WHERE user_id=$1`,[id.deletedMember])).rows.length,0);
        assert.equal((await q('SELECT * FROM public.get_platform_admin_overview_counts($1,$2)',[id.platform,user])).rows.length,1);
      }
    });
    await check('unauthorized, removed and suspended platform memberships denied',async()=>{
      for(const user of [id.ps,id.removed,id.suspended,id.staff]){
        await context(user,id.platform);
        assert.equal((await one('SELECT public.is_verified_platform_admin_context() AS allowed')).allowed,false);
        assert.equal((await q(`SELECT * FROM public.users WHERE user_id=$1`,[id.other])).rows.length,0);
        assert.equal((await q(`SELECT * FROM public.tenant_users WHERE tenant_id=$1`,[id.b])).rows.length,0);
        assert.equal((await q(`SELECT * FROM public.companies WHERE tenant_id=$1`,[id.b])).rows.length,0);
        await rejects(()=>q('SELECT * FROM public.get_platform_admin_overview_counts($1,$2)',[id.platform,user]),'42501');
      }
      await context(id.po,id.a);
      assert.equal((await one('SELECT public.is_verified_platform_admin_context() AS allowed')).allowed,false);
    });
    await check('cross-tenant writes remain denied for platform administrators',async()=>{
      await context(id.po,id.platform);
      assert.equal((await q(`UPDATE public.users SET full_name='forbidden' WHERE user_id=$1 RETURNING user_id`,[id.other])).rows.length,0);
      assert.equal((await q(`UPDATE public.companies SET business_name='forbidden' WHERE tenant_id=$1 RETURNING tenant_id`,[id.b])).rows.length,0);
      assert.equal((await q(`UPDATE public.tenant_users SET role_key='admin' WHERE tenant_id=$1 RETURNING user_id`,[id.b])).rows.length,0);
    });
    await check('helper ownership, fixed search_path, private execute ACLs and no role switching',async()=>{
      const funcs=(await q(`SELECT p.proname,r.rolname,p.prosecdef,p.proconfig,
        EXISTS(SELECT 1 FROM pg_catalog.aclexplode(coalesce(p.proacl,pg_catalog.acldefault('f',p.proowner))) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE') AS public_execute
        FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_roles r ON r.oid=p.proowner
        WHERE p.oid IN ('public.platform_admin_can_read_customer_tenant(uuid)'::regprocedure,'public.platform_admin_can_read_customer_user(uuid)'::regprocedure)`)).rows;
      assert.equal(funcs.length,2);for(const f of funcs){assert.equal(f.rolname,'ceopro_platform_overview_reader');assert.equal(f.prosecdef,true);assert.equal(f.public_execute,false);assert(f.proconfig.includes('search_path=pg_catalog, public, pg_temp'));}
      assert.equal((await one(`SELECT pg_has_role('ceopro_app','ceopro_platform_overview_reader','MEMBER') AS allowed`)).allowed,false);
      assert.equal((await one(`SELECT has_schema_privilege('ceopro_platform_overview_reader','public','CREATE') AS allowed`)).allowed,false);
      for(const table of ['public.companies','public.tenant_users']) for(const privilege of ['INSERT','UPDATE','DELETE']) {
        assert.equal((await one('SELECT has_table_privilege(\'ceopro_platform_overview_reader\',$1,$2) AS allowed',[table,privilege])).allowed,false);
      }
      // SET ROLE authorization uses session_user; this fixture session is administrative.
      // The live runner tests role-switch denial on a separate actual app connection.
      await q('CREATE TEMP TABLE companies(tenant_id uuid,business_type text,deleted_at timestamptz)');
      await q('CREATE TEMP TABLE tenant_users(user_id uuid,tenant_id uuid,role_key text,removed_at timestamptz,platform_status text)');
      await context(id.po,id.platform);
      assert.equal((await one('SELECT public.platform_admin_can_read_customer_user($1) AS allowed',[id.other])).allowed,true);
    });
    await check('every app-readable RLS table plans reads, updates and deletes without cycles',async()=>{
      const tables=(await q(`SELECT n.nspname,c.relname FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind='r' AND c.relrowsecurity AND has_table_privilege(current_user,c.oid,'SELECT') ORDER BY c.relname`)).rows;
      for(const [user,tenant] of [['',''],[id.staff,id.a],[id.po,id.platform]]){
        await context(user,tenant);
        for(const t of tables){
          const relation=`"${t.nspname}"."${t.relname}"`;
          await q(`SELECT * FROM ${relation} LIMIT 0`);
          if((await one('SELECT has_table_privilege(current_user,$1,\'DELETE\') AS allowed',[relation])).allowed) await q(`DELETE FROM ${relation} WHERE false`);
          if((await one('SELECT has_table_privilege(current_user,$1,\'UPDATE\') AS allowed',[relation])).allowed) {
            const col=(await one(`SELECT attname FROM pg_attribute WHERE attrelid=$1::regclass AND attnum>0 AND NOT attisdropped AND attgenerated='' ORDER BY attnum LIMIT 1`,[relation])).attname;
            await q(`UPDATE ${relation} SET "${col}"="${col}" WHERE false`);
          }
        }
      }
      console.log(`AUDIT ${tables.length} RLS tables in anonymous, customer and platform contexts`);
    });
    return checks;
  } finally { await q('ROLLBACK'); }
}
