import test,{mock} from 'node:test';
import assert from 'node:assert/strict';
import {randomBytes,randomUUID} from 'node:crypto';
import {isolatedDatabase,tenantFixture} from '../isolated/database.mjs';
let products=[],orders=[],legacy=false,requests=[],hook=null;
mock.module('../../src/modules/dataconnection/store/provider.client.ts',{namedExports:{storeProvider:async(_tenant,input)=>{
 requests.push(input);if(hook)await hook();
 if(input.action==='verify')return {contractVersion:2,verified:true,currency:'JOD'};
 return {...(!legacy?{contractVersion:2}:{}),items:input.action==='products'?products:orders.map(o=>({...o,modifiedAt:new Date(Date.now()-60000).toISOString()})),hasMore:false};
}}});
const stock=quantity=>({state:'managed',quantity,stockStatus:quantity===0?'outofstock':'instock',lowStockThreshold:5,stockOwnerExternalId:null});
const line=(id='1',total='10',quantity=3)=>({externalId:id,productExternalId:'101',name:'Tea',sku:'TEA001',quantity,unitPrice:(Number(total)/quantity).toFixed(4),total,currency:'JOD',date:'2026-10-17T09:00:00Z'});
function order(id='900',changes={}){
 const items=changes.items??[line()];const merchandise=items.reduce((n,i)=>n+Number(i.total),0).toFixed(4);
 const status=changes.status??'completed',paidAt=changes.paidAt===undefined?'2026-10-17T09:00:00Z':changes.paidAt;
 const shipping=changes.shipping??'2',fees=changes.fees??'0.5',tax=changes.tax??'1.6';
 const subtotal=(Number(merchandise)+Number(shipping)+Number(fees)).toFixed(4),total=(Number(subtotal)+Number(tax)).toFixed(4),refundedTotal=changes.refundedTotal??'0';
 const cancelled=['cancelled','refunded','failed','trash'].includes(status);
 return {externalId:id,status,modifiedAt:new Date(Date.now()-60000).toISOString(),lines:status==='completed'&&!cancelled?items:[],invoice:{currency:'JOD',issuedAt:new Date(Date.now()-60000).toISOString(),paidAt,paymentStatus:cancelled?'CANCELLED':paidAt?'PAID':'UNPAID',subtotal,tax,total,merchandise,shipping,fees,discount:'3',originalTotal:(Number(total)+Number(refundedTotal)).toFixed(4),refundedTotal,items}};
}
test('restricted store accounting: stock ownership, paid invoices, rounding, refunds, replay, rollback and RLS',async()=>{
 const f=await isolatedDatabase('ceopro_app',{maxConnections:10});let prisma;
 try{
  await f.db.exec("SET TIME ZONE 'UTC'");
  const a=await tenantFixture(f.db),b=await tenantFixture(f.db);
  await f.db.exec("INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type,aggregation_type,reset_cycle) VALUES('connected_data_sources','Sources','Sources','limit','max','lifetime') ON CONFLICT DO NOTHING");
  await f.db.query("INSERT INTO plan_features(plan_id,feature_id,limit_value) SELECT $1,feature_id,3 FROM features WHERE feature_code='connected_data_sources'",[a.planId]);
  await f.db.query("UPDATE products SET sku='TEA001' WHERE product_id=$1",[a.productId]);
  const manualStock=randomUUID(),manualInvoice=randomUUID();
  await f.db.query("INSERT INTO inventory(inventory_id,tenant_id,product_id,stock_quantity,safety_stock,reorder_level,warehouse_location) VALUES($1,$2,$3,7,2,3,'Manual warehouse')",[manualStock,a.tenantId,a.productId]);
  await f.db.query("INSERT INTO invoices(invoice_id,tenant_id,invoice_number,currency,total_amount,payment_status) VALUES($1,$2,'MANUAL-KEEP','JOD',20,'PAID')",[manualInvoice,a.tenantId]);
  await f.role('ceopro_app');process.env.DATABASE_URL=f.url;process.env.STORE_CONNECTOR_ENCRYPTION_KEY=randomBytes(32).toString('hex');
  ({prisma}=await import('../../src/config/database.ts'));
  const {storeConnections:c}=await import('../../src/modules/dataconnection/store/connections.repo.ts');
  const {syncStorePage}=await import('../../src/modules/dataconnection/store/sync.repo.ts');
  const scope={tenantId:a.tenantId,userId:a.userId};
  const connected=await c.connect(scope,{url:'https://accounting.example.test',consumerKey:'ck_'+'a'.repeat(40),consumerSecret:'cs_'+'b'.repeat(40),consent:true,syncFrequencyMinutes:60});
  const context=async t=>f.db.query("SELECT set_config('app.current_tenant_id',$1,false),set_config('app.current_user_id',$2,false)",[t.tenantId,t.userId]);
  const rows=async sql=>(await f.db.query(sql,[a.tenantId])).rows;
  const sync=async()=>{await c.sync(scope,connected.id);for(let i=0;i<2;i++){const result=await syncStorePage(scope,connected.id);assert.equal(result.status,'COMMITTED',JSON.stringify(result));}await context(a);};
  // Emulate an already-deployed v1 connection: an imported sale exists, but
  // no order-invoice link. The extension must reuse that sale while backfilling.
  await context(a);const legacySale=randomUUID();
  await f.db.query("INSERT INTO transactions(transaction_id,tenant_id,product_id,quantity_sold,unit_price,total_price,original_currency,transaction_date) VALUES($1,$2,$3,3,3.3333,10,'JOD','2026-10-17')",[legacySale,a.tenantId,a.productId]);
  await f.db.query("INSERT INTO store_sale_links(tenant_id,source_id,order_id,line_id,transaction_id) VALUES($1,$2,'900','1',$3)",[a.tenantId,connected.id,legacySale]);
  await f.db.query('UPDATE store_connections SET last_success_at=now() WHERE source_id=$1',[connected.id]);
  products=[{externalId:'101',name:'Tea',sku:'TEA001',price:'2.5',currency:'JOD',inventory:stock(31)},{externalId:'202',name:'Shared variation',sku:'VAR202',price:'3',currency:'JOD',inventory:{state:'shared',quantity:null,stockStatus:'instock',lowStockThreshold:null,stockOwnerExternalId:'303'}}];orders=[order()];
  await sync();
  let balances=await rows('SELECT * FROM inventory WHERE tenant_id=$1 ORDER BY warehouse_location');assert.equal(balances.length,2);assert.equal(balances.find(v=>v.inventory_id===manualStock).stock_quantity,7);assert.equal(balances.find(v=>v.inventory_id!==manualStock).stock_quantity,31);
  assert.equal(balances.find(v=>v.inventory_id!==manualStock).safety_stock,null,'Missing safety stock remains unknown');
  const shared=(await rows("SELECT * FROM store_inventory_links WHERE tenant_id=$1 AND external_id='202'"))[0];assert.equal(shared.inventory_id,null);assert.equal(shared.stock_state,'shared');
  const {productsRepo}=await import('../../src/modules/products/repo/products.repo.ts');
  const detail=await productsRepo.get(scope,a.productId);assert.equal(detail.inventory.currentStock,38);assert.equal(detail.inventory.safetyStock,null,'Unknown safety stock is not a restock assumption');
  const sourceStock=balances.find(v=>v.inventory_id!==manualStock).inventory_id;
  const links=await rows('SELECT * FROM store_order_links WHERE tenant_id=$1');assert.equal(links.length,1);const invoiceId=links[0].invoice_id;
  let invoice=(await rows("SELECT * FROM invoices WHERE tenant_id=$1 AND invoice_number LIKE 'WC-%'"))[0];assert.equal(invoice.payment_status,'PAID');assert.equal(Number(invoice.total_amount),14.1);assert.equal(Number(invoice.tax_amount),1.6);
  const item=(await rows('SELECT * FROM invoice_items WHERE tenant_id=$1'))[0];assert.equal(Number(item.total_price),10);assert.equal(Number(item.rounding_adjustment),0.0001);
  const transaction=(await rows('SELECT * FROM store_sale_links WHERE tenant_id=$1'))[0].transaction_id;assert.equal(transaction,legacySale);assert.equal(requests.find(r=>r.action==='orders').since,null);
  assert.equal((await rows("SELECT count(*)::int n FROM invoices WHERE tenant_id=$1 AND payment_status='PAID' AND currency='JOD'"))[0].n,2,'Dashboard paid invoice query sees manual + source invoice, not an extra transaction');
  const {getMainDashboardKPIs}=await import('../../src/modules/dashboard/repo/dashboard.repo.ts');
  const dashboard=await getMainDashboardKPIs(a.tenantId,a.userId,30);assert.equal(dashboard.metrics.find(m=>m.id==='totalSales').value,2);assert.equal(dashboard.metrics.find(m=>m.id==='revenues').value,34.1,'Actual dashboard counts paid invoice totals once, without adding the transaction again');
  products[0].inventory=stock(29);await sync();
  assert.equal((await rows('SELECT inventory_id FROM inventory WHERE tenant_id=$1 AND inventory_id<>\''+manualStock+'\''))[0].inventory_id,sourceStock);
  assert.equal((await rows('SELECT invoice_item_id FROM invoice_items WHERE tenant_id=$1'))[0].invoice_item_id,item.invoice_item_id);
  assert.equal((await rows('SELECT transaction_id FROM store_sale_links WHERE tenant_id=$1'))[0].transaction_id,transaction);
  assert.equal((await rows('SELECT invoice_id FROM store_order_links WHERE tenant_id=$1'))[0].invoice_id,invoiceId);
  // A source-owned balance retains locally edited planning values on refresh.
  await f.db.query('UPDATE inventory SET safety_stock=9,reorder_level=8 WHERE inventory_id=$1',[sourceStock]);products[0].inventory=stock(28);await sync();
  assert.equal((await rows('SELECT safety_stock FROM inventory WHERE tenant_id=$1 AND inventory_id<>\''+manualStock+'\''))[0].safety_stock,9);
  orders=[order('900',{items:[line('1','6',2)],tax:'0.96',refundedTotal:'4.64'}),order('901',{status:'processing'})];await sync();
  invoice=(await rows("SELECT * FROM invoices WHERE tenant_id=$1 AND invoice_number LIKE 'WC-%-900'"))[0];assert.equal(Number(invoice.total_amount),9.46);assert.equal(invoice.payment_status,'PAID');assert.equal((await rows('SELECT quantity_sold FROM transactions WHERE tenant_id=$1'))[0].quantity_sold,2);
  assert.equal((await rows('SELECT count(*)::int n FROM transactions WHERE tenant_id=$1'))[0].n,1,'Paid processing order has an invoice but no completed-sale transaction');
  orders=[order('900',{status:'refunded',items:[],shipping:'0',fees:'0',tax:'0',refundedTotal:'14.1'}),order('901',{status:'cancelled'})];await sync();
  assert.equal((await rows('SELECT count(*)::int n FROM transactions WHERE tenant_id=$1'))[0].n,0);assert.equal((await rows('SELECT count(*)::int n FROM invoice_items WHERE tenant_id=$1'))[0].n,1);
  assert.equal((await rows("SELECT count(*)::int n FROM invoices WHERE tenant_id=$1 AND payment_status='PAID'"))[0].n,1,'Refunded/cancelled invoices leave the manual paid invoice intact');
  orders=[order('902',{paidAt:null})];products[0].inventory={...stock(null),state:'unmanaged'};await sync();
  assert.equal((await rows('SELECT inventory_id FROM inventory WHERE tenant_id=$1')).length,1,'Unknown source stock is not converted to a zero balance');
  assert.equal((await rows('SELECT inventory_id FROM store_inventory_links WHERE tenant_id=$1 AND external_id=\'101\''))[0].inventory_id,null);
  assert.equal((await rows("SELECT payment_status FROM invoices WHERE tenant_id=$1 AND invoice_number LIKE 'WC-%-902'"))[0].payment_status,'UNPAID','Completed alone is not recorded-payment evidence');
  products[0].inventory=stock(0);await sync();assert.equal((await rows('SELECT stock_quantity FROM inventory WHERE tenant_id=$1 ORDER BY stock_quantity'))[0].stock_quantity,0);
  // Upgrade replays history once; ordinary later runs use a modified watermark.
  await f.db.query('UPDATE store_connections SET mapping_version=1 WHERE source_id=$1',[connected.id]);requests=[];await sync();assert.equal(requests.find(r=>r.action==='orders').since,null);
  requests=[];await sync();assert.ok(requests.find(r=>r.action==='orders').since);
  const last=(await c.status(scope,connected.id))[0].last_success_at;
  const countsBefore=(await rows('SELECT count(*)::int n FROM invoices WHERE tenant_id=$1'))[0].n;
  orders=[order('903'),{...order('904'),invoice:{...order('904').invoice,total:'999'}}];await c.sync(scope,connected.id);await syncStorePage(scope,connected.id);assert.equal((await syncStorePage(scope,connected.id)).code,'STORE_ORDER_TOTAL_MISMATCH');
  await context(a);assert.equal((await rows('SELECT count(*)::int n FROM invoices WHERE tenant_id=$1'))[0].n,countsBefore,'A bad order rolls back the whole page including earlier orders');assert.equal((await c.status(scope,connected.id))[0].last_success_at.getTime(),last.getTime());
  legacy=true;await c.sync(scope,connected.id);assert.equal((await syncStorePage(scope,connected.id)).code,'STORE_ADAPTER_UPGRADE_REQUIRED');legacy=false;
  await context(b);for(const table of ['store_inventory_links','store_order_links','store_order_item_links'])assert.equal((await f.db.query('SELECT * FROM '+table+' WHERE tenant_id=$1',[a.tenantId])).rows.length,0);
  await assert.rejects(f.db.query('INSERT INTO store_inventory_links(tenant_id,source_id,external_id,stock_state) VALUES($1,$2,\'666\',\'unmanaged\')',[a.tenantId,connected.id]),e=>e.code==='42501');
  await f.role('ceopro_market_dispatcher');for(const table of ['store_order_links','store_inventory_links'])await assert.rejects(f.db.query('SELECT * FROM '+table),e=>e.code==='42501');
  await f.role('ceopro_app');await context(a);orders=[order('905')];await c.sync(scope,connected.id);hook=async()=>{hook=null;await c.disconnect(scope,connected.id);};assert.equal((await syncStorePage(scope,connected.id)).code,'STORE_SYNC_CANCELLED');await context(a);assert.equal((await rows('SELECT count(*)::int n FROM invoices WHERE tenant_id=$1'))[0].n,countsBefore,'Disconnect preserves business history');
 }finally{if(prisma)await prisma.$disconnect();await f.close();}
});
