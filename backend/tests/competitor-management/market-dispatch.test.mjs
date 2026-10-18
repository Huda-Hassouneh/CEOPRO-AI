import assert from 'node:assert/strict';
import {mock,test} from 'node:test';
let allowed=true,cost=true,publishFailure=false,writes=[],publishes=[],event=null,failCompletion=false;
await mock.module('../../src/modules/competitors/client/market-redis.client.ts',{namedExports:{publishMarketEvent:async(url,stream,row)=>{assert.equal(url,'redis://example.test');publishes.push({stream,row});if(publishFailure)throw Error('connection');return '123-1';}}});
await mock.module('../../src/modules/competitors/client/market-cost-guard.client.ts',{namedExports:{collectionCostDecision:async(tenant,source)=>{assert.equal(tenant,'tenant');assert.equal(source,'source');if(cost===null)throw Error('COST_GUARD_NOT_CONFIGURED');return {allowed:cost,reason:'Saved margin 0.65 is below the 1.00 floor'};}}});
const tx={$queryRaw:async(parts,...values)=>{const sql=parts.join('?');if(sql.includes('FOR UPDATE SKIP LOCKED'))return event?[event]:[];if(sql.includes(' AS allowed'))return [{allowed}];throw Error(sql);},$executeRaw:async(parts,...values)=>{const sql=parts.join('?');writes.push({sql,values});if(failCompletion&&sql.includes("status='PUBLISHED'"))throw Error('DB completion failed');return 1;}};
const db={$transaction:async(fn)=>fn(tx)};
const {dispatchMarketEvent}=await import('../../src/modules/competitors/repo/market-dispatcher.repo.ts');
const reset=()=>{writes=[];publishes=[];allowed=true;cost=true;publishFailure=false;failCompletion=false;event={event_id:'event',tenant_id:'tenant',source_id:'source',kind:'COLLECTION',attempts:0,dedupe_key:'collection:source:1'};};
test('dispatcher distinguishes submission, eligibility cancellation, cost denial and transient delivery retries',async()=>{
 reset();assert.equal((await dispatchMarketEvent(db,'redis://example.test')).status,'PUBLISHED');assert.equal(publishes[0].stream,'market.scrape.requested');assert.ok(writes.at(-1).sql.includes("status='PUBLISHED'"));
 reset();allowed=false;assert.equal((await dispatchMarketEvent(db,'redis://example.test')).status,'CANCELLED');assert.equal(publishes.length,0);
 reset();cost=false;const denied=await dispatchMarketEvent(db,'redis://example.test');assert.equal(denied.status,'CANCELLED');assert.equal(denied.errorCode,'COST_MARGIN_BLOCKED');assert.equal(denied.sourceId,'source');assert.match(denied.reason,/margin 0.65/);assert.ok(writes[0].values.includes(denied.reason));assert.equal(publishes.length,0);assert.ok(writes[0].sql.includes('COST_MARGIN_BLOCKED'));
 reset();cost=null;assert.equal((await dispatchMarketEvent(db,'redis://example.test')).status,'RETRYING');assert.ok(writes[0].values.includes('COST_GUARD_NOT_CONFIGURED'));assert.equal(publishes.length,0);
 reset();publishFailure=true;assert.equal((await dispatchMarketEvent(db,'redis://example.test')).status,'RETRYING');assert.ok(writes[0].values.includes('REDIS_PUBLISH_FAILED'));assert.ok(!writes[0].sql.includes("status='PUBLISHED'"));
 reset();event={...event,kind:'DISCOVERY',source_id:null};await dispatchMarketEvent(db,'redis://example.test');assert.equal(publishes[0].stream,'market.discovery.requested');
 reset();failCompletion=true;await assert.rejects(dispatchMarketEvent(db,'redis://example.test'),/DB completion failed/);assert.equal(writes.length,1,'failed completion must rollback, not be rewritten as a Redis failure');
 reset();event=null;assert.equal(await dispatchMarketEvent(db,'redis://example.test'),null);
});
