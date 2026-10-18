import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {randomUUID} from 'node:crypto';
import {spawn} from 'node:child_process';
import {resolve} from 'node:path';
import {isolatedDatabase,tenantFixture} from '../isolated/database.mjs';

test('AI persistence contract: missing metadata reproduction, forward repair, restricted write and isolation',async()=>{
 const f=await isolatedDatabase('ceopro_app');
 try {
  const a=await tenantFixture(f.db),b=await tenantFixture(f.db);
  await f.db.exec("INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type,aggregation_type,reset_cycle) VALUES('tracked_competitors','Tracked','Tracked','limit','max','lifetime'),('connected_data_sources','Sources','Sources','limit','max','lifetime') ON CONFLICT DO NOTHING");
  await f.db.query("INSERT INTO plan_features(plan_id,feature_id,limit_value) SELECT $1,feature_id,10 FROM features WHERE feature_code IN ('tracked_competitors','connected_data_sources')",[a.planId]);
  await f.db.exec("INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type) VALUES('competitor_management','Competitors','Competitors','boolean') ON CONFLICT DO NOTHING");
  await f.db.query("INSERT INTO plan_features(plan_id,feature_id) SELECT $1,feature_id FROM features WHERE feature_code='competitor_management'",[a.planId]);
  const competitor=randomUUID(),source=randomUUID(),job=randomUUID(),mapping=randomUUID(),stage=randomUUID();
  await f.db.query("INSERT INTO global_competitors(global_competitor_id,competitor_name) VALUES($1,'Metadata fixture')",[competitor]);
  await f.db.query('INSERT INTO tenant_competitors(tenant_id,global_competitor_id) VALUES($1,$2)',[a.tenantId,competitor]);
  await f.db.query(`INSERT INTO data_sources(source_id,tenant_id,source_name,source_type,collection_method,policy_status,approval_reference,approved_by,approved_at,privacy_reviewed_at)
   VALUES($1,$2,'Metadata fixture','website','WEB_SCRAPE','ALLOWED','isolated permission',$3,now(),now())`,[source,a.tenantId,a.userId]);
  await f.db.query('INSERT INTO ingestion_jobs(job_id,tenant_id,source_id) VALUES($1,$2,$3)',[job,a.tenantId,source]);
  await f.db.query('INSERT INTO competitor_product_mappings(mapping_id,tenant_id,global_competitor_id,product_id,source_id,comparison_confirmed) VALUES($1,$2,$3,$4,$5,true)',[mapping,a.tenantId,competitor,a.productId,source]);
  await f.db.query("INSERT INTO market_observation_staging(staging_id,tenant_id,source_id,job_id,mapping_id,raw_payload,content_hash) VALUES($1,$2,$3,$4,$5,'{}',$6)",[stage,a.tenantId,source,job,mapping,'a'.repeat(64)]);
  const migration=readFileSync(new URL('../../prisma/migrations/20261016040000_align_market_video_metadata/migration.sql',import.meta.url),'utf8');
  await f.db.exec('ALTER TABLE market_observations DROP COLUMN view_count,DROP COLUMN creator_handle,DROP COLUMN content_date');
  await assert.rejects(f.db.query('SELECT view_count FROM market_observations'),e=>e.code==='42703');
  await f.db.exec(migration);await f.db.exec(migration); // also safe if AI SQL was already applied
  const item={tenant_id:a.tenantId,source_id:source,job_id:job,mapping_id:mapping,product_id:a.productId,global_competitor_id:competitor,_staging_id:stage,
   product_name:'Herbal Tea Collection',product_url:'https://example.test/tea',source_name:'Metadata fixture',competitor_name:'Metadata fixture',collection_method:'WEB_SCRAPE',
   price_amount:16,currency:'JOD',is_available:true,source_status:'ALLOWED',is_exact_data:true,match_score:1,match_method:'FUZZY_NAME',safety_status:'SAFE',captured_at:new Date().toISOString(),reviews:[]};
  const code=`import sys,json,psycopg2
from src.market_scraper.market_repository import save_market_record
d=json.load(sys.stdin)
c=psycopg2.connect(d['url'])
with c.cursor() as q:
 q.execute("SELECT set_config('app.current_tenant_id',%s,false),set_config('app.current_user_id',%s,false)",(d['item']['tenant_id'],d['user']))
 q.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
 assert q.fetchone()==(False,False)
print(json.dumps(save_market_record(c,d['item'])))
c.close()
`;
  await f.role('ceopro_app');
  const child=spawn(process.env.KEEL_TEST_PYTHON||'python',['-c',code],{cwd:resolve('../ai'),env:{...process.env,PYTHONPATH:resolve('../ai')},stdio:['pipe','pipe','pipe'],timeout:30000});
  let out='',err='';child.stdout.on('data',x=>out+=x);child.stderr.on('data',x=>err+=x);
  child.stdin.end(JSON.stringify({url:f.url+'?sslmode=disable&gssencmode=disable',item,user:a.userId}));
  const status=await new Promise((r,j)=>{child.once('error',j);child.once('exit',r)});
  assert.equal(status,0,err);assert.equal(JSON.parse(out).status,'PROMOTED');
  await f.role('ceopro_app');
  await f.db.query("SELECT set_config('app.current_tenant_id',$1,false),set_config('app.current_user_id',$2,false)",[a.tenantId,a.userId]);
  const row=(await f.db.query('SELECT view_count,creator_handle,content_date FROM market_observations')).rows[0];
  assert.deepEqual(row,{view_count:null,creator_handle:null,content_date:null});
  await f.db.exec("UPDATE market_observations SET view_count=42,creator_handle='fixture',content_date=now()");
  await assert.rejects(f.db.exec('UPDATE market_observations SET view_count=-1'),e=>e.code==='23514');
  assert.equal((await f.db.query('SELECT count(*)::int AS n FROM competitor_prices')).rows[0].n,1);
  await f.db.query("SELECT set_config('app.current_tenant_id',$1,false),set_config('app.current_user_id',$2,false)",[b.tenantId,b.userId]);
  assert.equal((await f.db.query('SELECT * FROM market_observations')).rows.length,0);
  assert.equal((await f.db.query('SELECT * FROM competitor_prices')).rows.length,0);
 } finally {await f.close()}
});
