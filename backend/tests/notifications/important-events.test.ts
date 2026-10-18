import test from 'node:test';import assert from 'node:assert/strict';import {randomUUID} from 'node:crypto';
import {buildTenantNotification} from '../../src/modules/tenant-notifications/tenant-notification.definition.js';
import {buildPlatformNotification} from '../../src/modules/platform-notifications/platform-notification.definition.js';
import type {TenantNotificationOutboxEvent} from '../../src/modules/tenant-notifications/tenant-notification.types.js';
const event=(type:string):TenantNotificationOutboxEvent=>({id:randomUUID(),tenant_id:randomUUID(),event_type:type,dedupe_key:randomUUID(),payload:{resourceId:randomUUID(),recommendationId:randomUUID()},status:'processing',attempts:1,occurred_at:new Date(),next_attempt_at:new Date(),created_at:new Date(),delivered_at:null,last_error_code:null});
for(const type of ['BUSINESS_RECOMMENDATION_READY','MARKET_ALERT_TRIGGERED','IMPORT_COMPLETED','IMPORT_FAILED','SUBSCRIPTION_CHANGED'])test(type+' has an explicit tenant domain permission',()=>{
 const definition=buildTenantNotification(event(type));assert.ok(definition.recipientPolicy.requiredPermissions.length);assert.ok(definition.resourceId);assert.match(definition.titleKey,/tenantNotifications/);
 if(type==='SUBSCRIPTION_CHANGED')assert.equal(definition.category,undefined);
 else assert.ok(definition.category);
});
for(const type of ['TENANT_REGISTERED','IMPORT_FAILED','SUBSCRIPTION_CHANGED'])test(type+' has a platform-only definition',()=>{
 const e=event(type),d=buildPlatformNotification(e);assert.ok(d.recipientPolicy.requiredPermissions.length);assert.match(d.titleKey,/platformNotifications/);
 if(type==='IMPORT_FAILED'){assert.equal(d.resourceId,e.tenant_id);assert.equal(d.resourceType,'company');}
});
test('malformed resource identifiers fail closed',()=>{const e=event('MARKET_ALERT_TRIGGERED');e.payload.resourceId='javascript:alert(1)';assert.throws(()=>buildTenantNotification(e));});
