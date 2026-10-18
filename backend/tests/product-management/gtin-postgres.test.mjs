import test from 'node:test';
import assert from 'node:assert/strict';
import express from 'express';
import bcrypt from 'bcrypt';
import {randomBytes} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {isolatedDatabase,tenantFixture} from '../isolated/database.mjs';
test('GTIN end to end: restricted API, legacy input, duplicates, imports, versions and tenant isolation',async()=>{
 const f=await isolatedDatabase('ceopro_app',{maxConnections:10});let prisma,server;
 try{
  const a=await tenantFixture(f.db),b=await tenantFixture(f.db),password='GtinFixture123!';
  for(const t of [a,b])await f.db.query('UPDATE users SET password_hash=$1 WHERE user_id=$2',[await bcrypt.hash(password,4),t.userId]);
  await f.db.exec("INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type) VALUES('competitor_management','Competitors','Competitors','boolean') ON CONFLICT DO NOTHING");
  for(const t of [a,b])await f.db.query("INSERT INTO plan_features(plan_id,feature_id) SELECT $1,feature_id FROM features WHERE feature_code='competitor_management'",[t.planId]);
  process.env.DATABASE_URL=f.url;process.env.JWT_SECRET=randomBytes(32).toString('hex');
  await f.role('ceopro_app');({prisma}=await import('../../src/config/database.ts'));
  const {default:auth}=await import('../../src/modules/auth/route/auth.route.ts');
  const {default:routes}=await import('../../src/modules/products/route/products.route.ts');
  const app=express();app.use(express.json());app.use('/auth',auth);app.use('/products',routes);app.use((e,_req,res,_next)=>res.status(500).json({message:e.message}));
  server=await new Promise(resolve=>{const s=app.listen(0,'127.0.0.1',()=>resolve(s));});const base=`http://127.0.0.1:${server.address().port}`;
  const login=async t=>{const r=await fetch(base+'/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:`${t.userId}@example.test`,password})});const j=await r.json();assert.equal(r.status,200,JSON.stringify(j));return {Authorization:`Bearer ${j.session.accessToken}`,'Content-Type':'application/json'};};
  const headers=await login(a),other=await login(b);
  const request=async(method,path,body,h=headers)=>{
   const r=await fetch(base+path,{method,headers:h,...(body===undefined?{}:{body:JSON.stringify(body)})});return {status:r.status,body:await r.json()};
  };
  const product=(sku,gtin)=>({name:{en:sku,ar:''},sku,price:'12.5000',costPrice:null,currency:'JOD',brand:{en:'',ar:''},category:{en:'',ar:''},description:{en:'',ar:''},...(gtin===undefined?{}:{gtin})});
  let r=await request('POST','/products',product('LEGACY'));assert.equal(r.status,201,JSON.stringify(r));const legacy=r.body.data.product;assert.equal(legacy.gtin,null);
  r=await request('POST','/products',product('FIRST','036000291452'));assert.equal(r.status,201,JSON.stringify(r));const first=r.body.data.product;
  assert.equal(first.gtin,'036000291452');assert.equal(first.gtin14,'00036000291452');
  r=await request('POST','/products',product('SECOND','00036000291452'));assert.equal(r.status,201);const second=r.body.data.product;assert.equal(second.gtinDuplicate,true);
  r=await request('GET',`/products/${first.id}`);assert.equal(r.body.data.product.gtinDuplicate,true);
  r=await request('POST','/products',product('OTHER','036000291452'),other);assert.equal(r.status,201);assert.equal(r.body.data.product.gtinDuplicate,false);
  assert.equal((await request('GET',`/products/${first.id}`,undefined,other)).status,404);
  r=await request('GET','/products?search=00036000291452');assert.equal(r.status,200);assert.equal(r.body.data.pagination.total,2);
  for(const gtin of [36000291452,'036000291453','00000000','1e12'])assert.equal((await request('POST','/products',product('BAD',gtin))).status,400);
  r=await request('PATCH',`/products/${first.id}`,{expectedVersion:first.version,price:'13'});assert.equal(r.status,200);assert.equal(r.body.data.product.gtin,first.gtin);const version=r.body.data.product.version;
  const historyBefore=(await request('GET',`/products/${first.id}`)).body.data.priceHistory.length;
  assert.equal((await request('PATCH',`/products/${first.id}`,{expectedVersion:first.version,gtin:null})).status,409);
  const preview=async text=>{const form=new FormData();form.append('file',new Blob([text],{type:'text/csv'}),'gtins.csv');const response=await fetch(base+'/products/gtin-import/preview',{method:'POST',headers:{Authorization:headers.Authorization},body:form});return {status:response.status,body:await response.json()};};
  r=await preview('sku,gtin\nFIRST,4006381333931\nLEGACY,96385074');assert.equal(r.status,200,JSON.stringify(r));const rows=r.body.data.rows.map(({productId,expectedVersion,gtin})=>({productId,expectedVersion,gtin}));
  assert.equal((await request('POST','/products/gtin-import/apply',{rows:[...rows,{productId:second.id,expectedVersion:9999,gtin:'96385074'}]})).status,409);
  assert.equal((await request('GET',`/products/${first.id}`)).body.data.product.gtin,'036000291452','failed batch rolls back all rows');
  r=await request('POST','/products/gtin-import/apply',{rows});assert.equal(r.status,200,JSON.stringify(r));assert.equal(r.body.data.updated,2);
  assert.equal((await request('POST','/products/gtin-import/apply',{rows})).status,409,'stale replay cannot overwrite');
  assert.equal((await preview('sku,gtin\nMISSING,96385074')).status,400);
  assert.equal((await request('POST','/products/gtin-import/apply',{rows},other)).status,404);
  assert.equal((await request('POST','/products/gtin-import/apply',{rows,tenant_id:b.tenantId})).status,400);
  assert.equal((await request('POST','/products/gtin-import/apply',{rows},{})).status,401);
  r=await request('GET',`/products/${first.id}`);const latest=r.body.data.product;
  r=await request('PATCH',`/products/${first.id}`,{expectedVersion:latest.version,gtin:''});assert.equal(r.status,200);assert.equal(r.body.data.product.gtin,null);
  // Database validates direct writers too; test every accepted length and the
  // new check constraint without relying on the HTTP validator.
  await f.db.query("SELECT set_config('app.current_tenant_id',$1,false),set_config('app.current_user_id',$2,false)",[a.tenantId,a.userId]);
  for(const gtin of ['96385074','036000291452','4006381333931','10012345000017'])await f.db.query('UPDATE products SET gtin=$1 WHERE product_id=$2',[gtin,legacy.id]);
  await assert.rejects(f.db.query('UPDATE products SET gtin=$1 WHERE product_id=$2',['036000291453',legacy.id]),e=>e.code==='23514');
  const history=(await f.db.query('SELECT count(*)::int AS n FROM product_price_history WHERE tenant_id=$1 AND product_id=$2',[a.tenantId,first.id])).rows[0].n;
  assert.equal(history,historyBefore,'GTIN-only changes do not create price history');
  // Explicitly deny product-write permission while keeping read access.
  await f.role('postgres');await f.db.query("INSERT INTO system_roles(role_key,role_name,permissions) VALUES('gtin-reader','GTIN reader','{}')");
  await f.db.query("UPDATE tenant_users SET role_key='gtin-reader' WHERE tenant_id=$1 AND user_id=$2",[a.tenantId,a.userId]);await f.role('ceopro_app');
  assert.equal((await request('PATCH',`/products/${first.id}`,{expectedVersion:version,gtin:null})).status,403);
  assert.equal((await preview('sku,gtin\nFIRST,96385074')).status,403);
  assert.equal((await request('POST','/products/gtin-import/apply',{rows})).status,403);
 } finally {if(server)await new Promise(r=>server.close(r));await prisma?.$disconnect();await f.close();}
});
