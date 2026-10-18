import test from 'node:test';import assert from 'node:assert/strict';import {spawn} from 'node:child_process';import {resolve} from 'node:path';
import {isolatedDatabase,tenantFixture} from '../isolated/database.mjs';
test('Python saves candidates without billing reads; only Node can activate within subscription capacity',async()=>{
 const f=await isolatedDatabase('ceopro_app',{maxConnections:10});
 try{
 const fixtures={};for(const name of ['limited','other','zero','unlimited','inactive','missing_module','missing_capacity'])fixtures[name]=await tenantFixture(f.db);
 await f.db.exec(`INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type) VALUES('competitor_management','Competitors','Competitors','boolean') ON CONFLICT DO NOTHING;
 INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type,aggregation_type,reset_cycle) VALUES('tracked_competitors','Tracked','Tracked','limit','max','lifetime'),('connected_data_sources','Sources','Sources','limit','max','lifetime') ON CONFLICT DO NOTHING;`);
 for(const [name,limit] of Object.entries({limited:2,other:1,zero:0,unlimited:null,inactive:1,missing_module:2,missing_capacity:2})){
 const t=fixtures[name];
 if(name!=='missing_module')await f.db.query(`INSERT INTO plan_features(plan_id,feature_id) SELECT $1,feature_id FROM features WHERE feature_code='competitor_management'`,[t.planId]);
 if(name!=='missing_capacity')await f.db.query(`INSERT INTO plan_features(plan_id,feature_id,limit_value) SELECT $1,feature_id,$2 FROM features WHERE feature_code='tracked_competitors'`,[t.planId,limit]);
 await f.db.query(`INSERT INTO plan_features(plan_id,feature_id,limit_value) SELECT $1,feature_id,100 FROM features WHERE feature_code='connected_data_sources'`,[t.planId]);
 }
 await f.db.query("UPDATE subscriptions SET status='cancelled' WHERE id=$1",[fixtures.inactive.subscriptionId]);
 await f.role('ceopro_app');
 const runPython=async data=>{const child=spawn(process.env.KEEL_TEST_PYTHON||'python',['src/market_scraper/tests/keel_capacity_scenarios.py'],{cwd:resolve('../ai'),env:{...process.env,PYTHONPATH:resolve('../ai'),SCRAPER_DATABASE_URL:f.url+'?sslmode=disable&gssencmode=disable&connect_timeout=5',SCRAPER_ACTOR_USER_ID:fixtures.limited.userId,SCRAPER_DB_POOL_MIN_SIZE:'1',SCRAPER_DB_POOL_MAX_SIZE:'1'},stdio:['pipe','pipe','pipe']});
 let log='';child.stdout.on('data',x=>log+=x);child.stderr.on('data',x=>log+=x);child.stdin.end(JSON.stringify(data));
 const code=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',resolve);});assert.equal(code,0,log);return log.trim();};
 const discovered=JSON.parse(await runPython(fixtures));
 process.env.DATABASE_URL=f.url;const {prisma}=await import('../../src/config/database.ts');
 try{
 const {competitorsRepo:repo}=await import('../../src/modules/competitors/repo/competitors.repo.ts');
 const scope=name=>({tenantId:fixtures[name].tenantId,userId:fixtures[name].userId});
 for(const name of ['limited','other','unlimited'])assert.equal((await repo.track(scope(name),discovered[name].competitorId,true)).isTracked,true);
 for(const name of ['zero','inactive','missing_module','missing_capacity'])await assert.rejects(repo.track(scope(name),discovered[name].competitorId,true));
 assert.equal((await repo.track(scope('limited'),discovered.limited.domainId,true)).isTracked,true);
 assert.equal((await repo.list(scope('limited'))).capacity.remaining,0);
 fixtures.limited.trackedCompetitorId=discovered.limited.competitorId;await runPython({...fixtures,_recheck:true});
 await assert.rejects(repo.track(scope('other'),discovered.limited.competitorId,true),e=>e.code==='RESOURCE_NOT_FOUND');
 console.log('PASS actual Python product/domain discovery without legacy billing, untracked suggestions and no approval bypass; Node alone activates and enforces finite/unlimited/zero/inactive/missing grants and tenant isolation');
 }finally{await prisma.$disconnect();}
 }finally{await f.close();}
});
