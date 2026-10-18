import test,{mock} from 'node:test';
import assert from 'node:assert/strict';
let listWhere,countWhere,delivered=0;
const tx={
 $executeRaw:async()=>0,$queryRaw:async()=>[],
 tenantNotification:{findMany:async({where})=>{listWhere=where;return [];},create:async()=>{throw Error('Must not create a withdrawn notification');}},
 tenantNotificationReceipt:{count:async({where})=>{countWhere=where;return 0;}},
 tenantNotificationOutbox:{updateMany:async()=>{delivered++;return {count:1};}}
};
const db={$transaction:async fn=>fn(tx)};
await mock.module('../../src/config/database.ts',{namedExports:{prisma:db}});
await mock.module('../../src/config/notification-worker-database.ts',{namedExports:{notificationWorkerPrisma:db}});
const repo=await import('../../src/modules/tenant-notifications/repo/tenant-notification.repo.ts');
const {dispatchTenantNotification}=await import('../../src/modules/tenant-notifications/tenant-notification.dispatcher.ts');
test('hidden market notifications are excluded before pagination and unread count without filtering other categories',async()=>{
 await repo.listForRecipient({tenantId:'tenant',recipientUserId:'user',limit:10});
 await repo.countUnreadForRecipient({tenantId:'tenant',recipientUserId:'user'});
 assert.deepEqual(listWhere.eventType,{not:'MARKET_ALERT_TRIGGERED'});
 assert.deepEqual(countWhere.notification.is.eventType,{not:'MARKET_ALERT_TRIGGERED'});
 assert.equal(listWhere.tenantId,'tenant');assert.equal(countWhere.recipientUserId,'user');
});
test('old market outbox events finish without creating a visible notification',async()=>{
 await dispatchTenantNotification({id:'event',event_type:'MARKET_ALERT_TRIGGERED'});
 assert.equal(delivered,1);
});
