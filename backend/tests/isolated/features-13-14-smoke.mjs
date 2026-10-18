import test from 'node:test';import assert from 'node:assert/strict';import {randomUUID} from 'node:crypto';import {isolatedDatabase,tenantFixture} from './database.mjs';
test('forward migrations, restricted trigger publisher, notification atomicity and tenant isolation',async()=>{
 const f=await isolatedDatabase('ceopro_app');try{
 const a=await tenantFixture(f.db),b=await tenantFixture(f.db);
 const roles=(await f.db.query(`SELECT rolname,rolsuper,rolbypassrls,rolcanlogin FROM pg_roles WHERE rolname IN ('ceopro_app','ceopro_event_publisher','ceopro_notification_worker')`)).rows;
 assert.equal(roles.length,3);for(const r of roles){assert.equal(r.rolsuper,false);assert.equal(r.rolbypassrls,false);if(r.rolname==='ceopro_event_publisher')assert.equal(r.rolcanlogin,false);}
 assert.equal((await f.db.query(`SELECT count(*)::int n FROM platform_notification_outbox WHERE tenant_id=$1 AND event_type='TENANT_REGISTERED'`,[a.tenantId])).rows[0].n,1);
 await f.role('ceopro_app');await f.db.query(`SELECT set_config('app.current_tenant_id',$1,false),set_config('app.current_user_id',$2,false)`,[a.tenantId,a.userId]);
 assert.equal((await f.db.query(`SELECT count(*)::int n FROM business_recommendations WHERE tenant_id=$1`,[b.tenantId])).rows[0].n,0);
 await assert.rejects(f.db.query(`SELECT public.publish_important_event()`),/permission denied/);
 await f.db.query(`UPDATE subscriptions SET status='past_due' WHERE tenant_id=$1`,[a.tenantId]);
 assert.equal((await f.db.query(`SELECT count(*)::int n FROM tenant_notification_outbox WHERE event_type='SUBSCRIPTION_CHANGED' AND tenant_id=$1`,[a.tenantId])).rows[0].n,2);
 await f.db.query(`UPDATE subscriptions SET status='past_due' WHERE tenant_id=$1`,[a.tenantId]);
 assert.equal((await f.db.query(`SELECT count(*)::int n FROM tenant_notification_outbox WHERE event_type='SUBSCRIPTION_CHANGED' AND tenant_id=$1`,[a.tenantId])).rows[0].n,2);
 }finally{await f.close();}
});
