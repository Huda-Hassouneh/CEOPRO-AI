import pg from 'pg';
import dotenv from 'dotenv';
dotenv.config({quiet:true});
const url=process.env.KEEL_RLS_TEST_APP_URL || process.env.DATABASE_URL;
if(!url) throw new Error('Configure DATABASE_URL in backend/.env');
const db=new pg.Client({connectionString:url,connectionTimeoutMillis:10000});
try {
  await db.connect();
  const report={};
  report.identity=(await db.query(`SELECT current_database() AS database,current_user AS runtime,rolsuper,rolbypassrls
    FROM pg_roles WHERE rolname=current_user`)).rows;
  report.tables=(await db.query(`SELECT c.relname,r.rolname AS owner,c.relrowsecurity,c.relforcerowsecurity
    FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner
    WHERE c.oid IN ('public.users'::regclass,'public.tenant_users'::regclass,'public.companies'::regclass)`)).rows;
  report.policies=(await db.query(`SELECT tablename,policyname,roles,cmd,qual,with_check FROM pg_policies
    WHERE schemaname='public' AND tablename IN ('users','tenant_users','companies') ORDER BY tablename,policyname`)).rows;
  report.functions=(await db.query(`SELECT p.proname,r.rolname AS owner,p.prosecdef,p.proconfig,p.proacl,pg_get_functiondef(p.oid) AS definition
    FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner JOIN pg_namespace n ON n.oid=p.pronamespace
    WHERE n.nspname='public' AND p.proname IN ('get_current_tenant','auth_login_memberships','is_verified_platform_admin_context','platform_admin_can_read_customer_tenant','platform_admin_can_read_customer_user') ORDER BY p.proname`)).rows;
  report.reader=(await db.query(`SELECT rolname,rolcanlogin,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,
    pg_has_role('ceopro_app',oid,'MEMBER') AS runtime_membership FROM pg_roles WHERE rolname='ceopro_platform_overview_reader'`)).rows;
  console.log(JSON.stringify(report,null,2));
} finally {await db.end();}
