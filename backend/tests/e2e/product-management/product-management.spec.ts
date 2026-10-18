import { test, expect } from '@playwright/test';
import { Pool } from 'pg';
// Opt-in against a dedicated QA database; never called by the contract suite.
const token=process.env.PRODUCT_TEST_ACCESS_TOKEN;
const tenant=process.env.PRODUCT_TEST_TENANT_ID;
const user=process.env.PRODUCT_TEST_USER_ID;
const database=process.env.PRODUCT_TEST_DATABASE_URL;
const api=(process.env.PRODUCT_TEST_API_URL || 'http://127.0.0.1:5000').replace(/\/$/,'');
const enabled=!!(token && tenant && user && database);
test.skip(!enabled,'Configure PRODUCT_TEST_ACCESS_TOKEN, PRODUCT_TEST_TENANT_ID, PRODUCT_TEST_USER_ID and PRODUCT_TEST_DATABASE_URL for the dedicated QA tenant.');
test('create, edit, initial/currency price audit, stale edit, archive and restore persist in PostgreSQL',async({request})=>{
 if(!database || !/(^|[_-])(test|testing|qa|e2e)([_-]|$)/.test(new URL(database).pathname.replace(/^\//,'')) || process.env.NODE_ENV==='production') throw new Error('Use a dedicated QA database.');
 const pool=new Pool({connectionString:database,max:1});
 const headers={Authorization:`Bearer ${token}`};
 let id:string|undefined;
 const facts=async()=>{const client=await pool.connect();try{await client.query('BEGIN READ ONLY');await client.query("SELECT set_config('app.current_tenant_id',$1,true),set_config('app.current_user_id',$2,true)",[tenant,user]);
 const product=await client.query('SELECT tenant_id,current_price::text,currency,version,deleted_at FROM products WHERE tenant_id=$1 AND product_id=$2',[tenant,id]);
 const history=await client.query('SELECT old_price::text,new_price::text,old_currency,currency FROM product_price_history WHERE tenant_id=$1 AND product_id=$2 ORDER BY changed_at,price_history_id',[tenant,id]);
 await client.query('COMMIT');return {product:product.rows[0],history:history.rows};}catch(error){await client.query('ROLLBACK');throw error;}finally{client.release();}};
 try{
  const list=await request.get(`${api}/products`,{headers});expect(list.ok()).toBeTruthy();const catalog=(await list.json()).data;
  expect(catalog.canEdit).toBe(true);expect(catalog.capacity.included).toBe(true);
  expect(catalog.currencies.length).toBeGreaterThanOrEqual(2);
  const currency=catalog.currencies[0],otherCurrency=catalog.currencies[1];
  const name=`Catalog QA ${Date.now()}`;
  const created=await request.post(`${api}/products`,{headers,data:{name:{en:name,ar:'منتج اختبار'},sku:`QA-${Date.now()}`,price:'0',costPrice:null,currency,brand:{en:'',ar:''},category:{en:'',ar:''},description:{en:'',ar:''}}});
  expect(created.status()).toBe(201);let product=(await created.json()).data.product;id=product.id;
  let db=await facts();expect(db.product.tenant_id).toBe(tenant);expect(Number(db.product.current_price)).toBe(0);expect(db.history).toHaveLength(1);expect(db.history[0].old_price).toBeNull();
  const search=await request.get(`${api}/products?search=${encodeURIComponent(name)}&sort=name`,{headers});expect((await search.json()).data.products.some((p:any)=>p.id===id)).toBe(true);
  const updated=await request.patch(`${api}/products/${id}`,{headers,data:{expectedVersion:product.version,price:'1.2345',currency:otherCurrency}});expect(updated.ok()).toBeTruthy();const oldVersion=product.version;product=(await updated.json()).data.product;
  db=await facts();expect(db.product.current_price).toBe('1.2345');expect(db.history).toHaveLength(2);expect(db.history[1].old_currency).toBe(currency);expect(db.history[1].currency).toBe(otherCurrency);
  const stale=await request.patch(`${api}/products/${id}`,{headers,data:{expectedVersion:oldVersion,price:'9'}});expect(stale.status()).toBe(409);expect((await stale.json()).error.code).toBe('PRODUCT_STALE_EDIT');
  const archived=await request.delete(`${api}/products/${id}`,{headers,data:{expectedVersion:product.version}});expect(archived.ok()).toBeTruthy();product=(await archived.json()).data.product;db=await facts();expect(db.product.deleted_at).toBeTruthy();expect(db.history).toHaveLength(2);
  const restored=await request.post(`${api}/products/${id}/restore`,{headers,data:{expectedVersion:product.version}});expect(restored.ok()).toBeTruthy();expect((await facts()).product.deleted_at).toBeNull();
 }finally{
  // Leave the test product archived with its audit records rather than erase history.
  if(id){const response=await request.get(`${api}/products/${id}`,{headers});if(response.ok()){const p=(await response.json()).data.product;if(!p.archivedAt)await request.delete(`${api}/products/${id}`,{headers,data:{expectedVersion:p.version}});}}
  await pool.end();
 }
});
