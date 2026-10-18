import assert from 'node:assert/strict';import {test} from 'node:test';
import {requestCollection,requestDiscovery} from '../../src/modules/competitors/repo/market-tracking.requests.ts';
test('request bridge keeps tenant scope, catalog-only discovery, and reuses pending source work',async()=>{
 const saved={event_id:'existing',status:'PENDING'};let inserts=0;
 const tx={$executeRawUnsafe:async(sql,key)=>{assert.match(sql,/advisory/);assert.equal(key,'market-source:source');},$queryRaw:async(parts,...values)=>{const sql=parts.join('?');assert.equal(values[0],'tenant');if(sql.includes('FROM market_tracking_outbox'))return [saved];if(sql.includes('INSERT INTO'))inserts++;return [saved];}};
 assert.equal(await requestCollection(tx,'tenant','source',1440,true),saved);assert.equal(inserts,0);
 const request=await requestDiscovery(tx,'tenant');assert.equal(request.discoveryScope,'tenant_catalog');assert.equal(request.status,'PENDING');assert.equal(request.eventId,'existing');
});
