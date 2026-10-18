import assert from 'node:assert/strict';
import { mock, test } from 'node:test';
let feature=true, permission=true, limit=2, rows=[], audit=[], calls=[];
const scope={tenantId:'tenant',userId:'user'};
const find=(where)=>rows.find(row=>row.tenant_id===where.tenant_id && row.product_id===where.product_id) || null;
const tx={
 $queryRaw:async(parts,...values)=>{const sql=parts.join('?');calls.push({sql,values});
  if(sql.includes('product_capacity_for_tenant'))return [{current_usage:BigInt(rows.filter(r=>r.tenant_id===values[0]&&!r.deleted_at).length),limit_value:limit,is_unlimited:limit===null,included:true}];return [];},
 $executeRawUnsafe:async(sql,key)=>{assert.match(sql,/pg_advisory_xact_lock/);assert.equal(key,'products-capacity:tenant');},
 tenantUser:{findFirst:async({where})=>{assert.equal(where.tenantId,scope.tenantId);assert.equal(where.userId,scope.userId);return permission?{role:{permissions:{'products.write':true}}}:null;}},
 company:{findUnique:async()=>({primaryCurrency:'JOD',supportedCurrencies:['JOD','USD']})},
 products:{findFirst:async({where})=>find(where),findMany:async({where})=>rows.filter(r=>r.tenant_id===where.tenant_id&&(!('deleted_at'in where)||r.deleted_at===where.deleted_at)&&(!where.product_id?.not||r.product_id!==where.product_id.not)),
 create:async({data})=>{const row={...data,product_id:`product-${rows.length}`,version:1,deleted_at:null,created_at:new Date(),updated_at:new Date()};rows.push(row);return row;},
 update:async({where,data})=>{const row=find(where.tenant_id_product_id);assert.ok(row);Object.assign(row,data,{version:row.version+1,updated_at:new Date()});return row;}},
 inventory:{findMany:async({where})=>{assert.deepEqual(where,{tenant_id:'tenant',product_id:rows[0].product_id});return [{inventory_id:'stock',stock_quantity:0,safety_stock:0,reorder_level:0,warehouse_location:'Main',updated_at:new Date()}];}},
 product_price_history:{findMany:async({where,take})=>{assert.equal(where.tenant_id,'tenant');assert.equal(take,100);return audit;}}
};
await mock.module('../../src/config/database.ts',{namedExports:{prisma:{$transaction:async(fn,opts)=>{assert.deepEqual(opts,{maxWait:10000,timeout:30000});return fn(tx);}}}});
await mock.module('../../src/modules/features/repo/usage.repo.ts',{namedExports:{getFeatureAccessInfo:async(tenant,code)=>{assert.equal(tenant,'tenant');assert.equal(code,'product_management');return {subscription:{},planFeature:feature?{}:null};}}});
const { productsRepo, retainedImportAliases }=await import('../../src/modules/products/repo/products.repo.ts');
const input={name:{en:'Tea',ar:''},sku:'TEA-1',price:'0',costPrice:null,currency:'JOD',brand:{en:'',ar:''},category:{en:'',ar:''},description:{en:'',ar:''}};
test('catalog repository preserves identity, price precision and zero stock; enforces access, versions and archive capacity',async()=>{
 const created=await productsRepo.create(scope,input);const id=created.product.id;
 assert.equal(created.product.price,'0');assert.deepEqual(calls[0].values,['tenant','user']);
 assert.equal(rows[0].created_by_user_id,'user');assert.equal(rows[0].tenant_id,'tenant');
 await assert.rejects(productsRepo.create(scope,input),e=>e.code==='PRODUCT_DUPLICATE');
 await assert.rejects(productsRepo.create(scope,{...input,sku:'USD-1',currency:'EUR'}),e=>e.code==='INVALID_PARAMETER');
 permission=false;await assert.rejects(productsRepo.update(scope,id,{expectedVersion:1,price:'1'}),e=>e.code==='FORBIDDEN');permission=true;
 await assert.rejects(productsRepo.update(scope,id,{expectedVersion:2,price:'1'}),e=>e.code==='PRODUCT_STALE_EDIT');
 const updated=await productsRepo.update(scope,id,{expectedVersion:1,name:{en:'New tea',ar:''},price:'1.2345'});
 assert.equal(updated.product.id,id);assert.equal(updated.product.price,'1.2345');assert.equal(updated.product.version,2);
 assert.deepEqual(rows[0].metadata.import_name_aliases,['tea']);
 audit=[{price_history_id:'audit',old_price:'0',new_price:'1.2345',old_currency:'JOD',currency:'JOD',changed_at:new Date(),changed_by_user_id:'user'}];
 const details=await productsRepo.get(scope,id);assert.equal(details.inventory.currentStock,0);assert.equal(details.priceHistory[0].oldPrice,'0');
 const archived=await productsRepo.archive(scope,id,2);assert.ok(archived.product.archivedAt);assert.equal(rows.length,1);assert.equal(audit.length,1);
 assert.ok((await productsRepo.get(scope,id)).product.archivedAt);
 await assert.rejects(productsRepo.update(scope,id,{expectedVersion:3,price:'2'}),e=>e.code==='PRODUCT_ARCHIVED');
 limit=0;await assert.rejects(productsRepo.archive(scope,id,3,true),e=>e.code==='PRODUCT_CAPACITY_EXCEEDED');
 limit=2;const restored=await productsRepo.archive(scope,id,3,true);assert.equal(restored.product.archivedAt,null);assert.equal(restored.product.version,4);
 rows.push({...rows[0],tenant_id:'other',product_id:'foreign'});await assert.rejects(productsRepo.get(scope,'foreign'),e=>e.code==='RESOURCE_NOT_FOUND');
 feature=false;await assert.rejects(productsRepo.get(scope,id),e=>e.code==='FORBIDDEN');feature=true;
 assert.deepEqual(retainedImportAliases({import_job_id:'job',import_name_aliases:['tea']},{en:'New tea'},{en:'Newest tea'}),{import_job_id:'job',import_name_aliases:['tea','new tea']});
});
