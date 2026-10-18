import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {randomBytes,randomUUID,createHmac} from 'node:crypto';
import {createServer} from 'node:net';
import {writeFileSync,mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {resolve,join} from 'node:path';
import express from 'express';
import jwt from 'jsonwebtoken';
import {isolatedDatabase,tenantFixture} from '../isolated/database.mjs';
const gid=(kind,id)=>`gid://shopify/${kind}/${id}`;
const amount=value=>({shopMoney:{amount:String(value),currencyCode:'JOD'}});
const page=nodes=>({nodes,pageInfo:{hasNextPage:false,endCursor:null}});
const variant=id=>({id:gid('ProductVariant',id),title:'Black',sku:'SHREAL'+id,barcode:'4006381333931',price:'12.5',product:{id:gid('Product',id),title:'Real Webcam',status:'ACTIVE'},inventoryItem:{id:gid('InventoryItem',id),tracked:true,inventoryLevels:page([{location:{id:gid('Location','11')},quantities:[{name:'on_hand',quantity:4}]},{location:{id:gid('Location','12')},quantities:[{name:'on_hand',quantity:0}]}])}});
const rawOrder=id=>({id:gid('Order',id),createdAt:new Date(Date.now()-86400000).toISOString(),processedAt:new Date(Date.now()-86400000).toISOString(),updatedAt:new Date(Date.now()-60000).toISOString(),cancelledAt:null,closed:false,test:true,currencyCode:'JOD',displayFinancialStatus:'PAID',displayFulfillmentStatus:'UNFULFILLED',transactions:[{kind:'SALE',status:'SUCCESS',processedAt:new Date(Date.now()-86400000).toISOString()}],currentSubtotalPriceSet:amount(10),currentShippingPriceSet:amount(2),currentTotalPriceSet:amount(13.6),currentTotalTaxSet:amount(1.6),currentTotalAdditionalFeesSet:null,currentTotalDutiesSet:null,currentTotalDiscountsSet:amount(5),totalPriceSet:amount(13.6),totalRefundedSet:amount(0),email:'must-not-import@example.test',lineItems:page([{id:gid('LineItem',id),name:'Real Webcam — Black',sku:'SHREAL101',quantity:3,currentQuantity:3,variant:{id:gid('ProductVariant',101)},priceAfterAllDiscountsBeforeTaxesSet:amount(10)}])});

test('Shopify real Node/Python transport + restricted DB: OAuth, cursor sync, accounting, token rotation, lifecycle, RLS and privacy',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'keel-shopify-')),fixturePath=join(dir,'fixture.json');
 const fixture={scopes:['read_products','read_orders','read_inventory','read_locations'],catalog:[[variant(101)],[variant(102)]],orders:[[rawOrder(900)]]};
 const save=()=>writeFileSync(fixturePath,JSON.stringify(fixture));save();
 const port=await new Promise(r=>{const s=createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>r(p));});});
 const secret=randomBytes(32).toString('hex');
 const child=spawn(process.env.KEEL_TEST_PYTHON||'python',[resolve('tests/store-connectors/shopify-fixture.py'),String(port),fixturePath],{cwd:resolve('../ai'),env:{...process.env,PYTHONPATH:resolve('../ai'),STORE_CONNECTOR_SERVICE_SECRET:secret},stdio:['ignore','ignore','pipe']});
 let childError='';child.stderr.on('data',b=>childError+=String(b));
 const realFetch=globalThis.fetch;let tokenCalls=0;
 globalThis.fetch=async(url,options)=>{
  if(String(url)==='https://test-shop.myshopify.com/admin/oauth/access_token'){
   tokenCalls++;const body=JSON.parse(options.body);assert.equal(body.client_id,'fixture-client');
   assert.ok(body.code||body.refresh_token);
   return new Response(JSON.stringify({access_token:'fixture-access-'+tokenCalls,refresh_token:'fixture-refresh-'+tokenCalls,expires_in:3600,refresh_token_expires_in:7776000,scope:fixture.scopes.join(',')}),{status:200});
  }
  return realFetch(url,options);
 };
 let f,prisma,dispatcher,server;
 try{
  for(let i=0;i<100;i++){try{if((await realFetch(`http://127.0.0.1:${port}/health`)).ok)break;}catch{}if(i===99)throw Error('Adapter fixture did not start: '+childError);await new Promise(r=>setTimeout(r,100));}
  f=await isolatedDatabase('ceopro_app',{maxConnections:10});await f.db.exec("SET TIME ZONE 'UTC'");
  const a=await tenantFixture(f.db),b=await tenantFixture(f.db);
  await f.db.exec("INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type,aggregation_type,reset_cycle) VALUES('connected_data_sources','Sources','Sources','limit','max','lifetime') ON CONFLICT DO NOTHING");
  for(const t of [a,b])await f.db.query('INSERT INTO plan_features(plan_id,feature_id,limit_value) SELECT $1,feature_id,3 FROM features WHERE feature_code=\'connected_data_sources\'',[t.planId]);
  const manualInvoice=randomUUID(),manualStock=randomUUID();
  await f.db.query("INSERT INTO invoices(invoice_id,tenant_id,invoice_number,currency,total_amount,payment_status) VALUES($1,$2,'MANUAL-KEEP','JOD',20,'PAID')",[manualInvoice,a.tenantId]);
  await f.db.query("INSERT INTO inventory(inventory_id,tenant_id,product_id,stock_quantity,warehouse_location) VALUES($1,$2,$3,7,'Manual')",[manualStock,a.tenantId,a.productId]);
  process.env.DATABASE_URL=f.url;process.env.MARKET_DISPATCHER_DATABASE_URL=f.url.replace('ceopro_app@','ceopro_market_dispatcher@');
  process.env.STORE_CONNECTOR_SERVICE_SECRET=secret;process.env.STORE_CONNECTOR_ENCRYPTION_KEY=randomBytes(32).toString('hex');process.env.STORE_CONNECTOR_API_URL=`http://127.0.0.1:${port}`;
  process.env.SHOPIFY_CLIENT_ID='fixture-client';process.env.SHOPIFY_CLIENT_SECRET=secret;process.env.SHOPIFY_REDIRECT_URI='https://backend.example.test/integrations/shopify/callback';process.env.FRONTEND_URL='http://localhost:5173';process.env.JWT_SECRET=secret;
  await f.role('ceopro_app');
  ({prisma}=await import('../../src/config/database.ts'));
  const {default:publicRoutes}=await import('../../src/modules/dataconnection/store/shopify/public.routes.ts');
  const {default:dataRoutes}=await import('../../src/modules/dataconnection/route/dataconnection.route.ts');
  const {storeConnections:c}=await import('../../src/modules/dataconnection/store/connections.repo.ts');
  const {syncStorePage}=await import('../../src/modules/dataconnection/store/sync.repo.ts');
  const {openCredentials,sealCredentials}=await import('../../src/modules/dataconnection/store/vault.ts');
  const app=express();app.use('/integrations/shopify',publicRoutes);app.use(express.json());app.use('/data-connection',dataRoutes);
  server=await new Promise(r=>{const s=app.listen(0,'127.0.0.1',()=>r(s));});const base=`http://127.0.0.1:${server.address().port}`;
  const scope={tenantId:a.tenantId,userId:a.userId},other={tenantId:b.tenantId,userId:b.userId};
  const headers=t=>({'Content-Type':'application/json',Authorization:'Bearer '+jwt.sign({id:t.userId,user_id:t.userId,email:`${t.userId}@example.test`,tenant_id:t.tenantId},secret,{expiresIn:600})});
  const post=async(path,body,t=a)=>{const response=await fetch(base+path,{method:'POST',headers:headers(t),body:JSON.stringify(body)});return {status:response.status,body:await response.json()};};
  const context=async t=>f.db.query("SELECT set_config('app.current_tenant_id',$1,false),set_config('app.current_user_id',$2,false)",[t.tenantId,t.userId]);
  const rows=async(sql,values=[])=>{await context(a);return (await f.db.query(sql,values)).rows;};
  const authorize=async()=>{
   const begun=await post('/data-connection/store/shopify/authorize',{url:'https://test-shop.myshopify.com',consent:true,includeTestOrders:true,syncFrequencyMinutes:60});assert.equal(begun.status,200,JSON.stringify(begun));
   const oauthUrl=new URL(begun.body.data.authorizationUrl);assert.equal(oauthUrl.hostname,'test-shop.myshopify.com');
   const query=new URLSearchParams({shop:'test-shop.myshopify.com',state:oauthUrl.searchParams.get('state'),code:'fixture-code',timestamp:String(Math.floor(Date.now()/1000))});
   query.set('hmac',createHmac('sha256',secret).update([...query.entries()].sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=>`${k}=${v}`).join('&')).digest('hex'));
   const previous=tokenCalls,callback=await fetch(base+'/integrations/shopify/callback?'+query,{redirect:'manual'});assert.equal(callback.status,303);assert.equal(tokenCalls,previous,'Unauthenticated callback does not exchange/store credentials');
   const location=new URL(callback.headers.get('location'));assert.equal(location.origin,'http://localhost:5173');
   const params=new URLSearchParams(location.hash.slice(1));assert.equal(params.get('shopify_state'),query.get('state'));
   return params.get('shopify_ticket');
  };
  const ticket=await authorize();
  assert.equal((await post('/data-connection/store/shopify/complete',{ticket},b)).status,403,'Callback cannot connect a store to another tenant/account');
  const completed=await post('/data-connection/store/shopify/complete',{ticket});assert.equal(completed.status,200,JSON.stringify(completed));const id=completed.body.data.id;
  assert.equal((await post('/data-connection/store/shopify/complete',{ticket})).status,400,'One-use state blocks authorization replay');
  const sync=async()=>{await c.sync(scope,id);for(let i=0;i<10;i++){const result=await syncStorePage(scope,id);assert.equal(result.status,'COMMITTED',JSON.stringify(result));if((await c.status(scope,id))[0].status==='CONNECTED')return;}throw Error('Sync did not finish');};
  await sync();
  const count=async table=>Number((await rows(`SELECT count(*)::int n FROM ${table} WHERE tenant_id=$1`,[a.tenantId]))[0].n);
  assert.equal(await count('store_product_links'),2);assert.equal(await count('store_inventory_locations'),4);assert.equal(await count('inventory'),5);
  assert.equal(await count('store_order_links'),1);assert.equal(await count('store_sale_links'),1);
  assert.equal((await rows('SELECT payment_status FROM invoices WHERE invoice_id<>$1',[manualInvoice]))[0].payment_status,'PAID');
  const sales=await rows('SELECT transaction_id,quantity_sold,total_price,product_id FROM transactions WHERE tenant_id=$1',[a.tenantId]);assert.equal(sales[0].quantity_sold,3);assert.equal(Number(sales[0].total_price),10);
  assert.equal((await rows("SELECT gtin FROM products WHERE sku='SHREAL101'"))[0].gtin,'4006381333931');
  const {loadForecastGenerationInput}=await import('../../src/modules/forecasting/repo/forecasting.repo.ts');
  const forecastInput=await loadForecastGenerationInput({...scope,productId:sales[0].product_id});assert.equal(forecastInput.transactions[0].quantity,3);assert.equal(forecastInput.invalidRecords,0);
  const {getMainDashboardKPIs}=await import('../../src/modules/dashboard/repo/dashboard.repo.ts');const dashboard=await getMainDashboardKPIs(a.tenantId,a.userId,30);assert.equal(dashboard.metrics.find(m=>m.id==='revenues').value,33.6);
  assert.ok(!JSON.stringify(await rows('SELECT raw_payload_json FROM import_staging_rows WHERE tenant_id=$1',[a.tenantId])).includes('must-not-import'));
  await sync();assert.equal((await rows('SELECT transaction_id FROM transactions WHERE tenant_id=$1',[a.tenantId]))[0].transaction_id,sales[0].transaction_id);assert.equal(await count('invoices'),2);assert.equal(await count('inventory'),5);
  await assert.rejects(c.sync(other,id),/STORE_NOT_FOUND/);await context(b);assert.equal((await f.db.query('SELECT * FROM store_connections WHERE tenant_id=$1',[a.tenantId])).rows.length,0);
  await context(a);
  const ciphertext=(await rows('SELECT credentials FROM store_connections WHERE source_id=$1',[id]))[0].credentials;
  const credentials=openCredentials(ciphertext,a.tenantId,id);assert.equal(credentials.provider,'shopify');assert.ok(!ciphertext.includes('fixture-access'));
  const expiring=sealCredentials({...credentials,expiresAt:Date.now()-1},a.tenantId,id);
  await f.db.query('UPDATE store_connections SET credentials=$1 WHERE source_id=$2',[expiring,id]);const previousCalls=tokenCalls;await sync();assert.equal(tokenCalls,previousCalls+1);
  const rotated=openCredentials((await rows('SELECT credentials FROM store_connections WHERE source_id=$1',[id]))[0].credentials,a.tenantId,id);assert.notEqual(rotated.refreshToken,credentials.refreshToken);
  const repeated=await post('/data-connection/store/shopify/complete',{ticket:await authorize()});assert.equal(repeated.body.data.id,id,'Reauthorization reuses stable shop/source identity');
  const expiredTicket=await authorize();await context(a);await f.db.query("UPDATE store_oauth_states SET expires_at=now()-interval '1 second' WHERE tenant_id=$1 AND consumed_at IS NULL",[a.tenantId]);
  const callsBeforeExpired=tokenCalls;assert.equal((await post('/data-connection/store/shopify/complete',{ticket:expiredTicket})).status,400);assert.equal(tokenCalls,callsBeforeExpired);
  fixture.scopes.push('read_all_orders');save();const upgrade=await post('/data-connection/store/shopify/complete',{ticket:await authorize()});assert.equal(upgrade.status,200);
  assert.equal((await rows('SELECT mapping_version FROM store_connections WHERE source_id=$1',[id]))[0].mapping_version,1,'Additional order-history permission restarts the backfill');
  await sync();

  fixture.orders[0][0].displayFinancialStatus='PARTIALLY_REFUNDED';fixture.orders[0][0].lineItems.nodes[0].currentQuantity=2;fixture.orders[0][0].lineItems.nodes[0].priceAfterAllDiscountsBeforeTaxesSet=amount(6);fixture.orders[0][0].currentTotalPriceSet=amount(8.96);fixture.orders[0][0].currentTotalTaxSet=amount(.96);fixture.orders[0][0].totalRefundedSet=amount(4.64);save();await sync();
  assert.equal((await rows('SELECT quantity_sold FROM transactions WHERE tenant_id=$1',[a.tenantId]))[0].quantity_sold,2);
  fixture.orders[0][0].cancelledAt=new Date().toISOString();save();await sync();assert.equal(await count('transactions'),0);
  fixture.orders=[[rawOrder(900)]];fixture.catalog[0][0].inventoryItem.inventoryLevels.nodes[0].quantities[0].quantity=2;save();await sync();assert.equal(await count('transactions'),1);
  fixture.throttled=true;save();await c.sync(scope,id);const failed=await syncStorePage(scope,id);assert.equal(failed.code,'STORE_RATE_LIMITED');assert.equal(await count('store_sale_links'),1);fixture.throttled=false;save();
  const webhook=async(topic,body,event=randomUUID(),valid=true)=>{
   const raw=JSON.stringify(body),signature=createHmac('sha256',secret).update(raw).digest('base64');
   await f.role('ceopro_market_dispatcher');
   try{return await fetch(base+'/integrations/shopify/webhooks',{method:'POST',headers:{'Content-Type':'application/json','X-Shopify-Hmac-Sha256':valid?signature:'bad','X-Shopify-Shop-Domain':'test-shop.myshopify.com','X-Shopify-Topic':topic,'X-Shopify-Webhook-Id':event},body:raw});}
   finally{await f.role('ceopro_app');await context(a);}
  };
  assert.equal((await webhook('orders/updated',{},randomUUID(),false)).status,401);
  const event=randomUUID();assert.equal((await webhook('orders/updated',{},event)).status,200);assert.equal((await webhook('orders/updated',{},event)).status,200);
  await f.role('ceopro_market_dispatcher');await assert.rejects(f.db.query('SELECT credentials FROM store_connections'),e=>e.code==='42501');
  await assert.rejects(f.db.query('SELECT * FROM invoices'),e=>e.code==='42501');
  await assert.rejects(f.db.query('SELECT * FROM shopify_webhook_deliveries'),e=>e.code==='42501');
  await f.role('ceopro_app');await context(a);
  await assert.rejects(f.db.query("SELECT public.process_shopify_event('test-shop.myshopify.com','orders/updated','forged')"),e=>e.code==='42501');
  await c.sync(scope,id);assert.equal((await syncStorePage(scope,id)).status,'COMMITTED');
  assert.equal((await webhook('inventory_levels/update',{})).status,200);
  for(let i=0;i<5;i++){const result=await syncStorePage(scope,id);if(result.status==='IDLE')break;if((await c.status(scope,id))[0].status==='CONNECTED')break;}
  const connection=(await rows('SELECT next_run_at,sync_requested FROM store_connections WHERE source_id=$1',[id]))[0];assert.ok(new Date(connection.next_run_at)<=new Date(),'Events during a run request an immediate follow-up');
  assert.equal((await webhook('products/delete',{id:102})).status,200);assert.equal(await count('inventory'),3,'Deleted source product balances removed; manual stock retained');
  fixture.catalog=[[variant(101)]];save();await sync();
  const sourceBalance=(await rows("SELECT inventory_id FROM store_inventory_locations WHERE source_id=$1 AND external_id=$2 AND location_id=$3",[id,gid('ProductVariant',101),gid('Location',11)]))[0].inventory_id;
  await f.db.query('UPDATE inventory SET safety_stock=9,reorder_level=8 WHERE inventory_id=$1',[sourceBalance]);fixture.catalog[0][0].inventoryItem.inventoryLevels.nodes[0].quantities[0].quantity=2;save();await sync();
  const balance=(await rows('SELECT stock_quantity,safety_stock,reorder_level FROM inventory WHERE inventory_id=$1',[sourceBalance]))[0];assert.equal(balance.stock_quantity,2);assert.equal(balance.safety_stock,9);assert.equal(balance.reorder_level,8);
  fixture.catalog[0][0].inventoryItem.tracked=false;save();await sync();assert.equal(await count('inventory'),1,'Untracked inventory remains unknown, never an invented zero');
  fixture.catalog[0][0].inventoryItem.tracked=true;save();await sync();
  const requestEvent=randomUUID();assert.equal((await webhook('customers/data_request',{orders_requested:[900]},requestEvent)).status,200);
  const reports=await fetch(base+`/data-connection/store/${id}/privacy-reports`,{headers:headers(a)});assert.equal(reports.status,200);assert.ok((await reports.text()).includes(gid('Order',900)));
  assert.equal((await webhook('customers/redact',{orders_to_redact:[900]})).status,200);assert.equal(await count('store_sale_links'),0);assert.equal(await count('invoices'),1,'Source financial records erased; manual invoice preserved');
  await sync();assert.equal(await count('store_sale_links'),0,'Redacted orders cannot be silently reimported');
  fixture.orders=[[rawOrder(901)]];save();await sync();assert.equal(await count('store_sale_links'),1);
  assert.equal((await webhook('app/uninstalled',{})).status,200);const uninstalled=(await rows('SELECT status,credentials FROM store_connections WHERE source_id=$1',[id]))[0];assert.equal(uninstalled.status,'DISCONNECTED');assert.equal(uninstalled.credentials,null);
  await assert.rejects(c.sync(scope,id),/STORE_RECONNECT_REQUIRED/);
  assert.equal((await webhook('shop/redact',{})).status,200);assert.equal(await count('store_sale_links'),0);assert.equal(await count('store_product_links'),0);assert.equal(await count('store_inventory_locations'),0);assert.equal(await count('invoices'),1);assert.equal(await count('inventory'),1);
  assert.equal((await rows('SELECT source_url FROM data_sources WHERE source_id=$1',[id]))[0].source_url,null);
  await f.role('postgres');const role=(await f.db.query("SELECT rolcanlogin,rolsuper,rolbypassrls FROM pg_roles WHERE rolname='ceopro_shopify_events'")).rows[0];assert.equal(role.rolcanlogin,false);assert.equal(role.rolsuper,false);assert.equal(role.rolbypassrls,false);

 }finally{
  globalThis.fetch=realFetch;child.kill('SIGTERM');if(server)await new Promise(r=>server.close(r));if(prisma)await prisma.$disconnect();
  try{const m=await import('../../src/config/market-dispatcher-database.ts');await m.marketDispatcherPrisma.$disconnect();}catch{}
  if(f)await f.close();rmSync(dir,{recursive:true,force:true});
 }
});
