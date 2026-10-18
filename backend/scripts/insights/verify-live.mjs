// Read-only production-schema verification. Does not seed or mutate KEEL_DEV.
import pg from 'pg';import dotenv from 'dotenv';import assert from 'node:assert/strict';dotenv.config({quiet:true});
const c=new pg.Client({connectionString:process.env.DATABASE_URL,connectionTimeoutMillis:10000});
try{await c.connect();const role=(await c.query('SELECT current_user AS name,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')).rows[0];assert.equal(role.name,'ceopro_app');assert.equal(role.rolsuper,false);assert.equal(role.rolbypassrls,false);
 const tables=['business_recommendations','business_recommendation_runs','market_alert_events','market_alert_rules','tenant_notification_preferences'];
 const rows=(await c.query('SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=ANY($1::regclass[])',[tables.map(t=>'public.'+t)])).rows;
 assert.equal(rows.length,tables.length);for(const r of rows){assert.equal(r.relrowsecurity,true,r.relname);assert.equal(r.relforcerowsecurity,true,r.relname);}
 const helper=(await c.query(`SELECT p.prosecdef,r.rolname,r.rolsuper,r.rolbypassrls,r.rolcanlogin,p.proconfig,has_function_privilege(current_user,p.oid,'EXECUTE') AS can_execute FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner WHERE p.oid='public.publish_important_event()'::regprocedure`)).rows[0];
 assert.equal(helper.prosecdef,true);assert.equal(helper.rolname,'ceopro_event_publisher');assert.equal(helper.rolsuper,false);assert.equal(helper.rolbypassrls,false);assert.equal(helper.rolcanlogin,false);assert.equal(helper.can_execute,false);assert.ok(helper.proconfig.includes('search_path=pg_catalog, public'));
 await c.query('SELECT * FROM public.business_recommendations LIMIT 0');await c.query('SELECT * FROM public.market_alert_events LIMIT 0');await c.query('SELECT * FROM public.market_alert_rules LIMIT 0');
 console.log('PASS restricted runtime, required tables, FORCE RLS and trigger-only publisher ownership/grants');
}catch(e){console.error(e.message);process.exitCode=1;}finally{await c.end();}
