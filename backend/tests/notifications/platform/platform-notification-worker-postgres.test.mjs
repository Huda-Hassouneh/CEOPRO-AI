import test,{mock} from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {isolatedDatabase,tenantFixture} from '../../isolated/database.mjs';

test('restricted notification worker claims, delivers, retries and fails events without application-role writes',async()=>{
 const f=await isolatedDatabase('ceopro_app',{maxConnections:10});let app,worker,restore;
 try {
  const platform=await tenantFixture(f.db),customer=await tenantFixture(f.db),other=await tenantFixture(f.db);
  await f.db.query("UPDATE companies SET business_type='platform' WHERE tenant_id=$1",[platform.tenantId]);
  // Isolate explicitly-created events from fixture registration/subscription notices.
  await f.db.exec("UPDATE platform_notification_outbox SET status='delivered',delivered_at=now()");
  const first=randomUUID(),second=randomUUID(),third=randomUUID();
  for(const [id,tenant] of [[first,customer],[second,other],[third,customer]])
    await f.db.query(`INSERT INTO platform_notification_outbox(id,tenant_id,event_type,dedupe_key,payload,next_attempt_at) VALUES($1,$2,'TENANT_REGISTERED',$3,$4,$5)`,[id,tenant.tenantId,`worker-fixture:${id}`,JSON.stringify({resourceId:tenant.tenantId}),new Date('2000-01-01T00:00:00Z')]);
  process.env.DATABASE_URL=f.url;process.env.NOTIFICATION_WORKER_DATABASE_URL=f.url.replace('ceopro_app@','ceopro_notification_worker@');
  ({prisma:app}=await import('../../../src/config/database.ts'));
  ({notificationWorkerPrisma:worker}=await import('../../../src/config/notification-worker-database.ts'));
  await f.role('ceopro_app');
  await f.db.query(`SELECT set_config('app.current_tenant_id',$1,false),set_config('app.current_user_id',$2,false)`,[customer.tenantId,customer.userId]);
  await assert.rejects(app.platformNotificationOutbox.updateMany({where:{id:first},data:{status:'processing'}}),e=>e.code==='P2039' && /permission denied/.test(e.message));
  console.log('REPRODUCED application role 42501; application grants remain unchanged');
  // PGlite serializes sessions on one backend. Verify real SQL as the worker,
  // and independently guard both app delegates so mixed-client regressions fail.
  const wrongClient=()=>{throw new Error('Worker used application outbox client');};
  const delegate=app.platformNotificationOutbox,originalUpdate=delegate.updateMany,originalFind=delegate.findUnique;
  const wrongUpdate=mock.fn(wrongClient),wrongFind=mock.fn(wrongClient);
  delegate.updateMany=wrongUpdate;delegate.findUnique=wrongFind;
  restore=()=>{delegate.updateMany=originalUpdate;delegate.findUnique=originalFind;};
  await f.role('ceopro_notification_worker');
  const identity=(await worker.$queryRawUnsafe('SELECT current_user AS name,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user'))[0];
  assert.equal(identity.name,'ceopro_notification_worker');assert.equal(identity.rolsuper,false);assert.equal(identity.rolbypassrls,false);
  const {platformNotificationRepo:repo}=await import('../../../src/modules/platform-notifications/repo/platform-notification.repo.ts');
  const {dispatchPlatformNotification}=await import('../../../src/modules/platform-notifications/platform-notification.dispatcher.ts');
  const claimed=await repo.claimDueEvents(20);
  assert.equal(claimed.length,3);assert.ok(claimed.every(e=>e.status==='processing' && e.attempts===1));
  assert.deepEqual(await repo.claimDueEvents(20),[],'Lease prevents duplicate claims');
  const event=claimed.find(e=>e.id===first);
  await dispatchPlatformNotification(event);
  assert.equal((await worker.platformNotificationOutbox.findUnique({where:{id:first}})).status,'delivered');
  const notifications=await worker.platformNotification.findMany({where:{sourceTenantId:customer.tenantId}});
  assert.equal(notifications.length,1);assert.equal(notifications[0].platformTenantId,platform.tenantId);
  await dispatchPlatformNotification(event).then(()=>assert.fail('A stale delivered event must fail'),e=>assert.match(e.message,/processing state/));
  assert.equal((await worker.platformNotification.findMany({where:{sourceTenantId:customer.tenantId}})).length,1,'Replay does not duplicate final notifications');
  assert.equal(await repo.rescheduleOutboxEvent(second,{nextAttemptAt:new Date('2000-01-01T00:00:00Z'),errorCode:'TRANSIENT_FIXTURE'}),true);
  const retry=await repo.claimDueEvents(20);assert.equal(retry.length,1);assert.equal(retry[0].id,second);assert.equal(retry[0].attempts,2);
  assert.equal(await repo.markOutboxFailed(second,'FIXTURE_FAILED'),true);
  assert.equal(await repo.markOutboxFailed(third,'FIXTURE_FAILED'),true);
  assert.deepEqual(await repo.claimDueEvents(20),[]);
  assert.equal(wrongUpdate.mock.callCount(),0);
  assert.equal(wrongFind.mock.callCount(),0);
  restore();
  // Recipient APIs keep the ordinary application client and tenant perimeter.
  await f.role('ceopro_app');
  const ownerFeed=await repo.listForRecipient({platformTenantId:platform.tenantId,recipientUserId:platform.userId,limit:20});
  assert.equal(ownerFeed.items.length,1);
  const customerFeed=await repo.listForRecipient({platformTenantId:customer.tenantId,recipientUserId:customer.userId,limit:20});
  assert.equal(customerFeed.items.length,0);
  await assert.rejects(app.platformNotificationOutbox.updateMany({where:{id:first},data:{status:'pending'}}),e=>e.code==='P2039');
 }finally{restore?.();mock.restoreAll();if(app)await app.$disconnect();if(worker)await worker.$disconnect();await f.close();}
});
