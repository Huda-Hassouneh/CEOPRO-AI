import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {randomUUID} from 'node:crypto';
import {spawn} from 'node:child_process';
import {resolve} from 'node:path';
import {isolatedDatabase,tenantFixture} from '../isolated/database.mjs';

test('restricted Python GTIN flow: tenant reads, parsing, validation, atomic save and provenance',async()=>{
 const f=await isolatedDatabase('ceopro_app');
 try {
  const a=await tenantFixture(f.db),b=await tenantFixture(f.db);
  await f.db.exec("INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type,aggregation_type,reset_cycle) VALUES('tracked_competitors','Tracked','Tracked','limit','max','lifetime'),('connected_data_sources','Sources','Sources','limit','max','lifetime') ON CONFLICT DO NOTHING");
  await f.db.exec("INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type) VALUES('competitor_management','Competitors','Competitors','boolean') ON CONFLICT DO NOTHING");
  await f.db.query("INSERT INTO plan_features(plan_id,feature_id,limit_value) SELECT $1,feature_id,10 FROM features WHERE feature_code IN ('tracked_competitors','connected_data_sources','competitor_management')",[a.planId]);
  await f.db.query("UPDATE products SET product_name='{\"ar\":\"منتج باسم مختلف\"}',gtin='036000291452' WHERE product_id=$1",[a.productId]);
  const competitor=randomUUID(),source=randomUUID(),job=randomUUID(),mapping=randomUUID(),stage=randomUUID();
  await f.db.query("INSERT INTO global_competitors(global_competitor_id,competitor_name) VALUES($1,'GTIN fixture')",[competitor]);
  await f.db.query('INSERT INTO tenant_competitors(tenant_id,global_competitor_id) VALUES($1,$2)',[a.tenantId,competitor]);
  await f.db.query(`INSERT INTO data_sources(source_id,tenant_id,source_name,source_type,collection_method,policy_status,approval_reference,approved_by,approved_at,privacy_reviewed_at)
   VALUES($1,$2,'GTIN fixture','website','WEB_SCRAPE','ALLOWED','isolated permission',$3,now(),now())`,[source,a.tenantId,a.userId]);
  await f.db.query('INSERT INTO ingestion_jobs(job_id,tenant_id,source_id) VALUES($1,$2,$3)',[job,a.tenantId,source]);
  await f.db.query("INSERT INTO competitor_product_mappings(mapping_id,tenant_id,global_competitor_id,product_id,source_id,competitor_product_url,comparison_confirmed) VALUES($1,$2,$3,$4,$5,'https://example.test/tea',true)",[mapping,a.tenantId,competitor,a.productId,source]);
  await f.db.query("INSERT INTO market_observation_staging(staging_id,tenant_id,source_id,job_id,mapping_id,raw_payload,content_hash) VALUES($1,$2,$3,$4,$5,'{}',$6)",[stage,a.tenantId,source,job,mapping,'a'.repeat(64)]);
  const code=`import sys,json,psycopg2
from scrapy.http import HtmlResponse,Request
from src.market_scraper.data_access import load_scrape_targets
from src.market_scraper.tenant_discovery import _load_active_tenant_products
from src.market_scraper.spiders.market_source import MarketSourceSpider
from src.market_scraper.pipelines import ValidateMarketRecordPipeline
from src.market_scraper.market_repository import save_market_record
d=json.load(sys.stdin)
c=psycopg2.connect(d['url'])
with c.cursor() as q:
 q.execute("SELECT set_config('app.current_tenant_id',%s,false),set_config('app.current_user_id',%s,false)",(d['tenant'],d['user']))
 q.execute("SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
 assert q.fetchone()==('ceopro_app',False,False)
targets=load_scrape_targets(c,d['tenant'],d['source'])
assert len(targets)==1 and targets[0]['gtin']=='036000291452'
assert load_scrape_targets(c,d['other'],d['source'])==[]
catalog=_load_active_tenant_products(c,d['tenant'],False)
assert catalog[0]['gtin']=='036000291452'
s=MarketSourceSpider(source_url='https://example.test/tea',source_name='GTIN fixture',collection_method='STRUCTURED_DATA',targets_json=json.dumps(targets),tenant_id=d['tenant'],source_id=d['source'],job_id=d['job'])
p={'@type':'Product','name':'Completely different English title','gtin14':'00036000291452','offers':{'price':'16','priceCurrency':'JOD','availability':'https://schema.org/InStock'}}
html='<script type="application/ld+json">'+json.dumps(p)+'</script>'
r=HtmlResponse(url='https://example.test/tea',request=Request('https://example.test/tea'),body=html.encode(),encoding='utf-8')
item=list(s.parse_structured(r,targets[0]))[0]
item=ValidateMarketRecordPipeline().process_item(item)
item['_staging_id']=d['stage']
assert item['match_method']=='EXACT_GTIN'
try:
 print(json.dumps(save_market_record(c,item)))
except psycopg2.Error as e:
 c.rollback()
 print(json.dumps({'error':e.pgcode}))
c.close()
`;
  const run=async()=>{
   await f.role('ceopro_app');
   const child=spawn(process.env.KEEL_TEST_PYTHON||'python',['-c',code],{cwd:resolve('../ai'),env:{...process.env,PYTHONPATH:resolve('../ai')},stdio:['pipe','pipe','pipe'],timeout:30000});
   let out='',err='';child.stdout.on('data',x=>out+=x);child.stderr.on('data',x=>err+=x);
   child.stdin.end(JSON.stringify({url:f.url+'?sslmode=disable&gssencmode=disable',tenant:a.tenantId,user:a.userId,other:b.tenantId,source,job,stage}));
   const status=await new Promise((r,j)=>{child.once('error',j);child.once('exit',r)});assert.equal(status,0,err);return JSON.parse(out);
  };
  // Reproduce the old provenance constraint, then repair it forward.
  await f.db.exec("ALTER TABLE market_observations DROP CONSTRAINT market_observations_match_method_check;ALTER TABLE market_observations ADD CONSTRAINT market_observations_match_method_check CHECK(match_method IN ('EXACT_SKU','FUZZY_NAME'))");
  assert.equal((await run()).error,'23514');
  await f.role('postgres');assert.equal((await f.db.query('SELECT count(*)::int AS n FROM competitor_prices')).rows[0].n,0,'failed observation cannot leave a partial price');
  await f.db.exec(readFileSync(new URL('../../prisma/migrations/20261017000000_market_exact_gtin_method/migration.sql',import.meta.url),'utf8'));
  assert.equal((await run()).status,'PROMOTED');
  await f.db.query("SELECT set_config('app.current_tenant_id',$1,false),set_config('app.current_user_id',$2,false)",[a.tenantId,a.userId]);
  const row=(await f.db.query('SELECT match_method,match_score,raw_payload FROM market_observations')).rows[0];
  assert.equal(row.match_method,'EXACT_GTIN');assert.equal(Number(row.match_score),1);
  assert.equal(row.raw_payload.gtin_evidence.expected_gtin14,'00036000291452');
  assert.equal((await f.db.query('SELECT count(*)::int AS n FROM competitor_prices')).rows[0].n,1);
  await f.db.query("SELECT set_config('app.current_tenant_id',$1,false),set_config('app.current_user_id',$2,false)",[b.tenantId,b.userId]);
  assert.equal((await f.db.query('SELECT * FROM market_observations')).rows.length,0);
  assert.equal((await f.db.query('SELECT * FROM competitor_prices')).rows.length,0);
 }finally{await f.close()}
});
