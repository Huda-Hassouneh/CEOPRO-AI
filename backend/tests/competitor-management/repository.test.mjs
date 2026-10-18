import assert from 'node:assert/strict';
import {mock,test} from 'node:test';
let links=[],globals=[],enabled=true,permission=true,limit=1,updates=[],mappings=[];
const scope={tenantId:'tenant',userId:'user'};
const key=where=>where.tenant_id_global_competitor_id;
const joined=row=>row?{...row,global_competitors:globals.find(g=>g.global_competitor_id===row.global_competitor_id)}:null;
const tx={
 $queryRaw:async(parts,...values)=>{const sql=parts.join('?');if(sql.includes('competitor_product_candidates'))return [];if(sql.includes('set_config')) {assert.deepEqual(values,['tenant','user']);return [];}
 if(sql.includes('queue_market_tracking') || sql.includes('queue_competitor_discovery'))return [{event_id:'queued',status:'PENDING'}];if(sql.includes('market_tracking_outbox'))return [];
 assert.match(sql,/competitor_capacity_for_tenant/);assert.equal(values[0],'tenant');return [{current_usage:BigInt(links.filter(r=>r.tenant_id==='tenant'&&r.is_tracked).length),limit_value:enabled?limit:0,is_unlimited:enabled&&limit===null,included:enabled}];},
 $executeRawUnsafe:async(sql,value)=>{assert.match(sql,/pg_advisory_xact_lock/);assert.equal(value,'competitors-capacity:tenant');},
 tenantUser:{findFirst:async({where})=>{assert.equal(where.tenantId,'tenant');assert.equal(where.userId,'user');return {role:{permissions:permission?{'competitors.write':true}:{}}};}},
 global_competitors:{findMany:async()=>globals,create:async({data})=>{assert.equal(data.visibility,'PRIVATE');const row={...data,global_competitor_id:`global-${globals.length}`};globals.push(row);return row;}},
 tenant_competitors:{create:async({data})=>{const row={...data,added_at:new Date()};links.push(row);return joined(row);},findMany:async({where})=>links.filter(r=>r.tenant_id===where.tenant_id&&(!('is_tracked'in where)||r.is_tracked===where.is_tracked)).map(joined),
 findUnique:async({where})=>joined(links.find(r=>r.tenant_id===key(where).tenant_id&&r.global_competitor_id===key(where).global_competitor_id)),
 upsert:async({where,create,update})=>{let row=links.find(r=>r.tenant_id===key(where).tenant_id&&r.global_competitor_id===key(where).global_competitor_id);if(row)Object.assign(row,update);else{row={...create,added_at:new Date()};links.push(row);}return joined(row);},
 update:async({where,data})=>{const row=links.find(r=>r.tenant_id===key(where).tenant_id&&r.global_competitor_id===key(where).global_competitor_id);assert.ok(row);Object.assign(row,data);return joined(row);}},
 competitor_product_mappings:{findMany:async({where})=>{assert.equal(where.tenant_id,'tenant');return where.is_active===false?[]:mappings;},updateMany:async({where,data})=>{assert.equal(where.tenant_id,'tenant');updates.push({where,data});return {count:where.mapping_id==='mapping'?1:0};}},
 data_sources:{updateMany:async({where,data})=>{assert.equal(where.tenant_id,'tenant');assert.equal(where.policy_status,'ALLOWED');assert.deepEqual(where.source_type,{in:['website','WEB_SCRAPE']});assert.deepEqual(where.approved_by,{not:null});assert.equal(data.sync_frequency_minutes,1440);updates.push({where,data});return {count:where.source_id.in.length};}}
};
await mock.module('../../src/config/database.ts',{namedExports:{prisma:{$transaction:async(fn,options)=>{assert.deepEqual(options,{maxWait:10000,timeout:30000});return fn(tx);}}}});
await mock.module('../../src/modules/features/repo/usage.repo.ts',{namedExports:{getFeatureAccessInfo:async(tenant,code)=>{assert.equal(tenant,'tenant');assert.equal(code,'competitor_management');return {subscription:{},planFeature:enabled?{metadata:{configuration:{monitoringFrequencyMinutes:1440}}}:null};}}});
const {competitorsRepo:repo}=await import('../../src/modules/competitors/repo/competitors.repo.ts');
test('competitor lifecycle preserves IDs/history, deduplicates canonical websites and enforces access and capacity',async()=>{
 const first=await repo.create(scope,{name:'Tea store',website:'https://www.example.com/'});assert.equal(first.isTracked,true);
 const repeat=await repo.create(scope,{name:'Changed input',website:'http://example.com'});assert.equal(repeat.id,first.id);assert.equal(globals.length,1);assert.equal(links.length,1);
 await assert.rejects(repo.create(scope,{name:'Next',website:'https://next.example.com'}),e=>e.code==='COMPETITOR_CAPACITY_EXCEEDED');
 const list=await repo.list(scope);assert.equal(list.capacity.currentUsage,1);assert.equal(list.competitors.length,1);
 await repo.update(scope,first.id,'My display name');assert.equal(globals[0].competitor_name,'Tea store');assert.equal(links[0].custom_alias,'My display name');
 await repo.track(scope,first.id,false);assert.equal(links.length,1);assert.equal(globals.length,1);assert.equal((await repo.list(scope,'inactive')).competitors.length,1);
 limit=0;await assert.rejects(repo.track(scope,first.id,true),e=>e.code==='COMPETITOR_CAPACITY_EXCEEDED');limit=null;
 await repo.track(scope,first.id,true);assert.equal(links[0].is_tracked,true);
 permission=false;await assert.rejects(repo.update(scope,first.id,'Bad'),e=>e.code==='FORBIDDEN');permission=true;
 enabled=false;await assert.rejects(repo.profile(scope,first.id),e=>e.code==='FORBIDDEN');await assert.rejects(repo.track(scope,first.id,true),e=>e.code==='FORBIDDEN');
 await repo.track(scope,first.id,false);assert.equal((await repo.list(scope)).capacity.included,false);enabled=true;
 await assert.rejects(repo.track(scope,'foreign',false),e=>e.code==='RESOURCE_NOT_FOUND');
 mappings=[{source_id:'source'}];await repo.track(scope,first.id,true);const result=await repo.schedule(scope,first.id);assert.equal(result.updatedSources,1);
 await repo.confirm(scope,first.id,'mapping',true);assert.equal(updates.findLast(update=>'comparison_confirmed' in update.data).data.comparison_confirmed,true);
 await assert.rejects(repo.confirm(scope,first.id,'foreign-mapping',true),e=>e.code==='RESOURCE_NOT_FOUND');
 globals.push({...globals[0],global_competitor_id:'duplicate'});await assert.rejects(repo.create(scope,{name:'Duplicate',website:'https://example.com'}),e=>e.code==='COMPETITOR_IDENTITY_AMBIGUOUS');
});
test('profiles keep missing-price mappings visible, withhold unconfirmed/paused comparisons and retain same-currency history',async()=>{
 enabled=true;permission=true;links[0].is_tracked=true;
 const date=new Date(Date.now()-60000);
 const price=(id,currency,value,offset=0)=>({competitor_price_id:id,currency,scraped_price:value,observed_at:new Date(date.getTime()-offset),source_status:'ALLOWED',is_available:true,is_exact_data:true});
 mappings=[{mapping_id:'mapping',product_id:'product',comparison_confirmed:false,products:{product_name:{en:'Tea'},currency:'JOD',current_price:4},data_sources:null,competitor_product_url:'https://example.com/tea',competitor_product_sku:'TEA',competitor_prices:[price('new','JOD',5),price('old','JOD',4,60000),price('usd','USD',100)]},
 {mapping_id:'missing',product_id:'missing-product',comparison_confirmed:true,products:{product_name:{en:'Coffee'},currency:'JOD',current_price:4},data_sources:null,competitor_product_url:null,competitor_product_sku:null,competitor_prices:[]}];
 let detail=await repo.profile(scope,links[0].global_competitor_id);assert.equal(detail.mappedProducts.length,2);assert.equal(detail.mappedProducts[0].reason,'MATCH_UNCONFIRMED');assert.equal(detail.activity.length,0);
 mappings[0].comparison_confirmed=true;detail=await repo.profile(scope,links[0].global_competitor_id);assert.equal(detail.mappedProducts[0].competitorPrice,5);assert.equal(detail.mappedProducts[0].currency,'JOD');assert.equal(detail.activity.length,1);assert.equal(detail.activity[0].currency,'JOD');
 links[0].is_tracked=false;detail=await repo.profile(scope,links[0].global_competitor_id);assert.equal(detail.mappedProducts[0].reason,'TRACKING_PAUSED');assert.equal(detail.mappedProducts[0].competitorPrice,null);assert.equal(detail.activity.length,1);
 await assert.rejects(repo.profile(scope,'other-tenant-competitor'),e=>e.code==='RESOURCE_NOT_FOUND');
});
