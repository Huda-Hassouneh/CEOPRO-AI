import test from 'node:test';import assert from 'node:assert/strict';import express from 'express';import bcrypt from 'bcrypt';import {spawn} from 'node:child_process';import {resolve} from 'node:path';import {randomUUID,randomBytes} from 'node:crypto';import {isolatedDatabase,tenantFixture} from '../isolated/database.mjs';
test('authenticated Smart Alerts: saved rules, real Python price match, atomic bell event, cooldown and cross-tenant denial',async()=>{
 const f=await isolatedDatabase('ceopro_app',{maxConnections:10});let prisma,worker,server;
 try{
 await f.db.exec("SET TIME ZONE 'UTC'");const a=await tenantFixture(f.db),b=await tenantFixture(f.db),missing=await tenantFixture(f.db);
 await f.db.exec(`INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type) VALUES('system_alerts','Alerts','Alerts','boolean'),('competitor_management','Competitors','Competitors','boolean') ON CONFLICT DO NOTHING;
 INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type,aggregation_type,reset_cycle) VALUES('tracked_competitors','Tracked','Tracked','limit','max','lifetime') ON CONFLICT DO NOTHING;`);
 for(const t of [a,b])await f.db.query(`INSERT INTO plan_features(plan_id,feature_id,limit_value) SELECT $1,feature_id,10 FROM features WHERE feature_code IN ('system_alerts','competitor_management','tracked_competitors')`,[t.planId]);
 const password='SmartAlertFixture123!';for(const t of [a,b,missing])await f.db.query('UPDATE users SET password_hash=$1 WHERE user_id=$2',[await bcrypt.hash(password,10),t.userId]);
 const competitor=randomUUID(),mapping=randomUUID();await f.db.query(`INSERT INTO global_competitors(global_competitor_id,competitor_name) VALUES($1,'Fixture competitor')`,[competitor]);
 await f.db.query('INSERT INTO tenant_competitors(tenant_id,global_competitor_id) VALUES($1,$2)',[a.tenantId,competitor]);
 await f.db.query('INSERT INTO competitor_product_mappings(mapping_id,tenant_id,product_id,global_competitor_id,comparison_confirmed) VALUES($1,$2,$3,$4,true)',[mapping,a.tenantId,a.productId,competitor]);
 process.env.DATABASE_URL=f.url;process.env.NOTIFICATION_WORKER_DATABASE_URL=f.url;process.env.JWT_SECRET=randomBytes(32).toString('hex');
 await f.role('ceopro_app');({prisma}=await import('../../src/config/database.ts'));({notificationWorkerPrisma:worker}=await import('../../src/config/notification-worker-database.ts'));
 const {default:auth}=await import('../../src/modules/auth/route/auth.route.ts');const {default:alerts}=await import('../../src/modules/smart-alerts/route.ts');const {default:notifications}=await import('../../src/modules/tenant-notifications/route/tenant-notification.route.ts');
 const app=express();app.use(express.json());app.use('/auth',auth);app.use('/features/smart-alerts',alerts);app.use('/notifications',notifications);
 app.use((e,req,res,next)=>{console.error(e);res.status(500).json({message:String(e.message)});});
 server=await new Promise(r=>{const s=app.listen(0,'127.0.0.1',()=>r(s));});const base=`http://127.0.0.1:${server.address().port}`;
 const login=async t=>{const r=await fetch(base+'/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:`${t.userId}@example.test`,password})});assert.equal(r.status,200);return {Authorization:`Bearer ${(await r.json()).session.accessToken}`};};
 const own=await login(a),other=await login(b),none=await login(missing);
 const request=async(path,headers,method='GET',body)=>{const r=await fetch(base+path,{method,headers:{...headers,'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});const text=await r.text();return {status:r.status,data:text?(()=>{try{return JSON.parse(text)}catch{return {message:text}}})():null};};
 const rule={name:'Price drops at least 5%',global_competitor_id:competitor,operator:'LTE',threshold:-5,cooldown_minutes:60,is_active:true};
 assert.equal((await request('/features/smart-alerts',{})).status,401);assert.equal((await request('/features/smart-alerts',none)).status,403);
 assert.equal((await request('/features/smart-alerts/rules',other,'POST',rule)).status,404);
 const created=await request('/features/smart-alerts/rules',own,'POST',rule);assert.equal(created.status,201,JSON.stringify(created));const id=created.data.data.alert_rule_id;
 assert.equal((await request('/features/smart-alerts/rules/'+id,other,'PATCH',rule)).status,404);
 const derive=async()=>{
 const code=`from datetime import datetime,timezone,timedelta\nfrom decimal import Decimal\nfrom src.ai import db\nfrom src.market_scraper.market_repository import _derive_events\nc=db.app_role_connection('${a.tenantId}','${a.userId}')\ni={'tenant_id':'${a.tenantId}','mapping_id':'${mapping}','global_competitor_id':'${competitor}','source_id':None,'competitor_name':'Fixture competitor','product_name':'Tea','price_amount':90,'currency':'JOD','is_available':True,'product_url':'https://example.test/tea','captured_at':datetime.now(timezone.utc),'source_status':'ALLOWED','is_exact_data':True,'safety_status':'SAFE'}\nwith c.cursor() as cur:_derive_events(cur,i,(Decimal('100'),True,datetime.now(timezone.utc)-timedelta(hours=1),'JOD','ALLOWED',True))\nc.commit()\nc.close()\ndb.close_pool()\n`;
 const child=spawn(process.env.KEEL_TEST_PYTHON||'python',['-c',code],{cwd:resolve('../ai'),env:{...process.env,DATABASE_URL:f.url+'?sslmode=disable&gssencmode=disable&connect_timeout=5',APP_DB_PASSWORD:'fixture',APP_DB_POOL_MIN_SIZE:'1',APP_DB_POOL_MAX_SIZE:'1'},stdio:['ignore','pipe','pipe']});let logs='';child.stdout.on('data',x=>logs+=x);child.stderr.on('data',x=>logs+=x);const exit=await new Promise(r=>child.once('exit',r));assert.equal(exit,0,logs);
 };
 await derive();let feed=await request('/features/smart-alerts',own);assert.equal(feed.status,200,JSON.stringify(feed));assert.equal(feed.data.data.events.length,1);const event=feed.data.data.events[0];assert.equal(Number(event.observed_value),-10);assert.equal(event.trigger_facts.threshold,'-5.0000');
 await derive();assert.equal((await request('/features/smart-alerts',own)).data.data.total,1,'Cooldown suppresses a second matching collection');
 assert.equal((await request('/features/smart-alerts',other)).data.data.total,0);
 assert.equal((await request('/features/smart-alerts/events/'+event.alert_event_id+'/resolve',other,'POST')).status,404);
 const admin=async fn=>{await f.role('postgres');try{return await fn();}finally{await f.role('ceopro_app');}};
 const events=(await admin(()=>f.db.query(`SELECT * FROM tenant_notification_outbox WHERE tenant_id=$1 AND event_type='MARKET_ALERT_TRIGGERED'`,[a.tenantId]))).rows;assert.equal(events.length,1);
 const {tenantNotificationRepo:repo}=await import('../../src/modules/tenant-notifications/repo/tenant-notification.repo.ts');const {dispatchTenantNotification}=await import('../../src/modules/tenant-notifications/tenant-notification.dispatcher.ts');
 await f.role('ceopro_notification_worker');let claims=await repo.claimDueEvents(100);const claim=claims.find(e=>e.id===events[0].id);assert.ok(claim);await dispatchTenantNotification(claim);
 // Simulate the same leased event being retried after a worker interruption.
 await f.role('postgres');await f.db.query(`UPDATE tenant_notification_outbox SET status='processing' WHERE id=$1`,[claim.id]);await f.role('ceopro_notification_worker');await dispatchTenantNotification(claim);
 await f.role('ceopro_app');const bell=await request('/notifications',own);assert.equal(bell.status,200,JSON.stringify(bell));assert.equal(bell.data.data.items.filter(n=>n.eventType==='MARKET_ALERT_TRIGGERED').length,1,JSON.stringify(bell));
 assert.equal((await request('/notifications',other)).data.data.items.length,0);
 assert.equal((await request('/notifications/preferences',own)).data.data.length,3);
 assert.equal((await request('/notifications/preferences/market',own,'PUT',{enabled:false})).status,200);
 assert.equal((await request('/notifications/preferences',other)).data.data.find(x=>x.category==='market').enabled,true);
 await f.role('ceopro_notification_worker');assert.deepEqual(await repo.getTenantNotificationRecipientUserIds({tenantId:a.tenantId,requiredPermissions:['manage_catalog'],category:'market',requiredFeature:'system_alerts'}),[]);await f.role('ceopro_app');
 assert.equal((await request('/notifications/preferences/market',own,'PUT',{enabled:true})).status,200);
 await admin(()=>f.db.query(`DELETE FROM plan_features WHERE plan_id=$1 AND feature_id IN (SELECT feature_id FROM features WHERE feature_code='system_alerts')`,[a.planId]));
 assert.equal((await request('/features/smart-alerts',own)).status,403,'Node denies a removed paid feature');
 await f.role('ceopro_notification_worker');assert.deepEqual(await repo.getTenantNotificationRecipientUserIds({tenantId:a.tenantId,requiredPermissions:['manage_catalog'],category:'market',requiredFeature:'system_alerts'}),[],'Node worker suppresses paid-feature delivery after a downgrade');
 await f.role('postgres');await f.db.query(`INSERT INTO plan_features(plan_id,feature_id) SELECT $1,feature_id FROM features WHERE feature_code='system_alerts'`,[a.planId]);await f.role('ceopro_app');


 assert.equal((await request('/features/smart-alerts/events/'+event.alert_event_id+'/acknowledge',own,'POST')).status,200);
 assert.equal((await request('/features/smart-alerts?state=acknowledged',own)).data.data.total,1);
 assert.equal((await request('/features/smart-alerts/events/'+event.alert_event_id+'/resolve',own,'POST')).status,200);
 assert.equal((await request('/features/smart-alerts?state=resolved',await login(a))).data.data.total,1);
 assert.equal((await request('/features/smart-alerts/rules/'+id,own,'PATCH',{...rule,is_active:false})).status,200);
 await derive();assert.equal((await request('/features/smart-alerts?state=all',own)).data.data.total,1);
 // Deliver a new-tenant event exclusively to the platform owner.
 const platform=randomUUID();await f.role('postgres');
 await f.db.query(`INSERT INTO companies(tenant_id,business_name,business_type,country_code,primary_currency) VALUES($1,'Platform fixture','platform','JO','JOD')`,[platform]);
 await f.db.query(`INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES($1,$2,'owner')`,[platform,a.userId]);
 const {platformNotificationRepo:platformRepo}=await import('../../src/modules/platform-notifications/repo/platform-notification.repo.ts');
 const {dispatchPlatformNotification}=await import('../../src/modules/platform-notifications/platform-notification.dispatcher.ts');
 await f.role('ceopro_notification_worker');const platformClaim=(await platformRepo.claimDueEvents(100)).find(e=>e.tenant_id===a.tenantId&&e.event_type==='TENANT_REGISTERED');assert.ok(platformClaim);await dispatchPlatformNotification(platformClaim);
 await f.role('postgres');const deliveries=(await f.db.query(`SELECT n.source_tenant_id,r.recipient_user_id FROM platform_notifications n JOIN platform_notification_receipts r ON r.notification_id=n.id WHERE n.dedupe_key=$1`,[platformClaim.dedupe_key])).rows;
 assert.equal(deliveries.length,1);assert.equal(deliveries[0].source_tenant_id,a.tenantId);assert.equal(deliveries[0].recipient_user_id,a.userId);
 await f.db.query(`UPDATE tenant_users SET role_key='staff' WHERE tenant_id=$1 AND user_id=$2`,[a.tenantId,a.userId]);
 await f.role('ceopro_app');assert.equal((await request('/notifications',own)).data.data.items.length,0,'A role downgrade hides prior privileged receipts');
 console.log('PASS persisted rule, actual Python evaluation, cooldown, tenant isolation, alert lifecycle, worker retry dedupe and bell delivery');
 }finally{if(server)await new Promise(r=>server.close(r));if(prisma)await prisma.$disconnect();if(worker)await worker.$disconnect();await f.close();}
});
