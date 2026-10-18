import {randomUUID,createHash} from 'node:crypto';
import type {Prisma} from '../../../generated/prisma/client.js';
import {StoreError,productsSchema,ordersSchema,type StoreScope,type StoreProduct,type StoreOrder} from './contracts.js';
import {storeContext} from './context.js';
import {lockConnection} from './connections.repo.js';
import {validateProviderPage} from './provider-contract.js';
import {storeProvider} from './provider.client.js';
import {openCredentials} from './vault.js';
import {ensureImportedProduct} from '../repo/import-product.js';
import {parseSalesStagingRow} from '../service/sales-staging-row.js';
import {lockProductCatalog} from '../../products/repo/product-capacity.js';
import {getConnectedDataSourceCapacityInTransaction} from '../../features/repo/usage.repo.js';
import {ProductError} from '../../products/types/products.types.js';
import {ImportProductError} from '../repo/import-product.js';
import {commitStoreInventory,commitStoreLocations} from './inventory.repo.js';
import {validGtin} from '../../products/service/gtin.js';
import {exchangeShopifyToken} from './shopify/token.js';
import {sealCredentials} from './vault.js';
import {commitStoreInvoice,validateStoreOrder} from './invoices.repo.js';
type Progress={cursor?:string|null;mappingVersion?:number;phase:'products'|'orders';page:number;since:string|null;until:string;lastHash?:string;seen?:Array<{id:string;at:string}>};
type Lease={provider:'woocommerce'|'shopify';historyAccess:string;scope:StoreScope;sourceId:string;version:string;token:string;jobId:string;credentials:string;url:string;currency:string;progress:Progress};

async function auditRow(tx:Prisma.TransactionClient,lease:Lease,payload:Prisma.InputJsonValue,table:string,id:string){
 await tx.import_staging_rows.create({data:{tenant_id:lease.scope.tenantId,job_id:lease.jobId,raw_payload_json:payload,validation_status:'COMMITTED',committed_table:table,committed_record_id:id}});
}
async function linkProduct(tx:Prisma.TransactionClient,lease:Lease,product:Omit<StoreProduct,'inventory'>){
 const {tenantId}=lease.scope;
 const links=await tx.$queryRaw<Array<{product_id:string;owns_product:boolean}>>`SELECT product_id,owns_product FROM store_product_links WHERE tenant_id=${tenantId}::uuid AND source_id=${lease.sourceId}::uuid AND external_id=${product.externalId}`;
 let link=links[0];
 if(!link){
  const sku=product.sku||`${lease.provider==='shopify'?'sh':'wc'}-${lease.sourceId.slice(0,8)}-${product.externalId.split('/').at(-1)}`;
  const productId=await ensureImportedProduct(tx,tenantId,product.name,product.price,product.currency,lease.sourceId,new Map(),sku);
  const row=await tx.products.findFirstOrThrow({where:{tenant_id:tenantId,product_id:productId}});
  if(row.currency!==product.currency)throw new StoreError('STORE_PRODUCT_CONFLICT',409);
  const metadata=row.metadata as Record<string,unknown>|null;
  const owns=metadata?.import_job_id===lease.sourceId;
  const occupied=await tx.$queryRaw<Array<{external_id:string}>>`SELECT external_id FROM store_product_links WHERE tenant_id=${tenantId}::uuid AND source_id=${lease.sourceId}::uuid AND product_id=${productId}::uuid`;
  if(occupied.length)throw new StoreError('STORE_PRODUCT_CONFLICT',409);
  await tx.$executeRaw`INSERT INTO store_product_links(tenant_id,source_id,external_id,product_id,owns_product,parent_external_id) VALUES(${tenantId}::uuid,${lease.sourceId}::uuid,${product.externalId},${productId}::uuid,${owns},${product.parentExternalId??null})`;
  link={product_id:productId,owns_product:owns};
 }
 const current=await tx.products.findFirst({where:{tenant_id:tenantId,product_id:link.product_id,deleted_at:null}});
 if(!current)throw new StoreError('STORE_PRODUCT_ARCHIVED',409);
 if(link.owns_product){
  if(!current.current_price.equals(product.price)||current.currency!==product.currency)await tx.product_price_history.create({data:{tenant_id:tenantId,product_id:link.product_id,old_price:current.current_price,old_currency:current.currency,new_price:product.price,currency:product.currency,changed_by_user_id:lease.scope.userId}});
  if(product.parentExternalId)await tx.$executeRaw`UPDATE store_product_links SET parent_external_id=${product.parentExternalId} WHERE tenant_id=${tenantId}::uuid AND source_id=${lease.sourceId}::uuid AND external_id=${product.externalId}`;
  if(product.gtin&&!validGtin(product.gtin))throw new StoreError('STORE_INVALID_DATA');
  await tx.products.update({where:{product_id:link.product_id},data:{...(lease.provider==='shopify'&&product.active===true?{metadata:Object.fromEntries(Object.entries(current.metadata as Record<string,Prisma.InputJsonValue>??{}).filter(([key])=>key!=='store_source_inactive'))}:{}),...(product.gtin!==undefined?{gtin:product.gtin}:{}),product_name:{en:product.name},sku:product.sku||current.sku,current_price:product.price,currency:product.currency,updated_at:new Date()}});
 }
 return link.product_id;
}
async function commitOrder(tx:Prisma.TransactionClient,lease:Lease,order:StoreOrder){
 const {tenantId}=lease.scope;
 if(lease.provider==='shopify'){const excluded=await tx.$queryRaw<Array<{order_hash:string}>>`SELECT order_hash FROM store_order_exclusions WHERE tenant_id=${tenantId}::uuid AND source_id=${lease.sourceId}::uuid AND order_hash=${createHash('sha256').update(order.externalId).digest('hex')}`;if(excluded.length)return;}
 validateStoreOrder(order);
 const existingOrder=await tx.store_order_links.findUnique({where:{tenant_id_source_id_order_id:{tenant_id:tenantId,source_id:lease.sourceId,order_id:order.externalId}}});
 if(existingOrder&&existingOrder.source_modified_at>new Date(order.modifiedAt))return;
 const resolveProduct=async(line:StoreOrder['lines'][number])=>{
  const linked=await tx.$queryRaw<Array<{product_id:string}>>`SELECT product_id FROM store_product_links WHERE tenant_id=${tenantId}::uuid AND source_id=${lease.sourceId}::uuid AND external_id=${line.productExternalId}`;
  const id=linked[0]?.product_id??await linkProduct(tx,lease,{externalId:line.productExternalId,name:line.name,sku:line.sku,price:line.unitPrice,currency:line.currency});
  const product=await tx.products.findFirst({where:{tenant_id:tenantId,product_id:id,deleted_at:null}});
  if(!product)throw new StoreError('STORE_PRODUCT_ARCHIVED');
  if(product.currency!==line.currency)throw new StoreError('STORE_PRODUCT_CONFLICT');
  return id;
 };
 const invoiceId=await commitStoreInvoice(tx,lease.scope,lease.sourceId,order,resolveProduct,lease.provider);
 await auditRow(tx,lease,{order_id:order.externalId,status:order.status,...order.invoice},'invoices',invoiceId);
 const before=await tx.$queryRaw<Array<{line_id:string;transaction_id:string}>>`SELECT line_id,transaction_id FROM store_sale_links WHERE tenant_id=${tenantId}::uuid AND source_id=${lease.sourceId}::uuid AND order_id=${order.externalId}`;
 const retained=new Set(order.lines.map(line=>line.externalId));
 for(const old of before)if(!retained.has(old.line_id)){
  await tx.$executeRaw`DELETE FROM store_sale_links WHERE tenant_id=${tenantId}::uuid AND source_id=${lease.sourceId}::uuid AND order_id=${order.externalId} AND line_id=${old.line_id}`;
  await tx.transactions.deleteMany({where:{tenant_id:tenantId,transaction_id:old.transaction_id}});
 }
 for(const line of order.lines){
  const parsed=parseSalesStagingRow({product_name:line.name,quantity:line.quantity,unit_price:line.unitPrice,amount_raw:line.total,currency:line.currency,transaction_date:line.date,sku:line.sku});
  if(!parsed.ok)throw new StoreError('STORE_INVALID_SALE');
  const productId=await resolveProduct(line);
  if(!await tx.products.findFirst({where:{tenant_id:tenantId,product_id:productId,deleted_at:null}}))throw new StoreError('STORE_PRODUCT_ARCHIVED',409);
  const value=parsed.value,existing=before.find(row=>row.line_id===line.externalId);
  const data={product_id:productId,quantity_sold:value.quantity,unit_price:value.unitPrice,total_price:value.totalPrice,original_currency:value.currency,transaction_date:value.transactionDate,sale_source:lease.provider==='shopify'?'SHOPIFY':'WOOCOMMERCE'};
  const transactionId=existing?.transaction_id??randomUUID();
  if(existing)await tx.transactions.update({where:{transaction_id:transactionId},data});
  else {
   await tx.transactions.create({data:{...data,tenant_id:tenantId,transaction_id:transactionId}});
   await tx.$executeRaw`INSERT INTO store_sale_links(tenant_id,source_id,order_id,line_id,transaction_id) VALUES(${tenantId}::uuid,${lease.sourceId}::uuid,${order.externalId},${line.externalId},${transactionId}::uuid)`;
  }
  await auditRow(tx,lease,{order_id:order.externalId,...line},'transactions',transactionId);
 }
}

export async function claimStorePage(scope:StoreScope,sourceId:string):Promise<Lease|null>{
 return storeContext(scope,async tx=>{
  const c=await lockConnection(tx,scope,sourceId);
  if(!['QUEUED','CONNECTED','ERROR','SYNCING'].includes(c.status)||!c.credentials||c.attempts>=5||c.next_run_at>new Date()||c.lease_until&&c.lease_until>new Date())return null;
  const capacity=await getConnectedDataSourceCapacityInTransaction(tx,scope.tenantId);
  if(!capacity.included||!capacity.isUnlimited&&capacity.currentUsage>(capacity.limit??0))throw new StoreError('STORE_SOURCE_LIMIT',402);
  const source=await tx.data_sources.findFirst({where:{tenant_id:scope.tenantId,source_id:sourceId,is_active:true,collector_key:c.provider==='shopify'?'shopify_node':'woocommerce_node',policy_status:'ALLOWED'}});
  if(!source?.source_url)return null;
  let progress=c.progress as Partial<Progress>,jobId=c.job_id;
  if(progress.mappingVersion!==2){
   if(jobId)await tx.ingestion_jobs.updateMany({where:{tenant_id:scope.tenantId,job_id:jobId,job_status:{in:['QUEUED','PROCESSING']}},data:{job_status:'FAILED',error_log:'STORE_MAPPING_UPGRADED',ended_at:new Date()}});
   progress={};jobId=null;
  }
  if(!progress.phase||!jobId){
   if(!progress.phase)progress={mappingVersion:2,phase:'products',page:1,since:c.mapping_version>=2&&c.last_success_at?new Date(c.last_success_at.getTime()-300000).toISOString():null,until:new Date(Date.now()-2000).toISOString()};
   const job=await tx.ingestion_jobs.create({data:{tenant_id:scope.tenantId,source_id:sourceId,job_status:'PROCESSING',started_at:new Date()}});jobId=job.job_id;
  } else await tx.ingestion_jobs.updateMany({where:{tenant_id:scope.tenantId,job_id:jobId},data:{job_status:'PROCESSING',error_log:null,ended_at:null,heartbeat_at:new Date()}});
  const token=randomUUID();
  await tx.$executeRaw`UPDATE store_connections SET status='SYNCING',lease_token=${token}::uuid,lease_until=now()+interval '120 seconds',job_id=${jobId}::uuid,progress=${JSON.stringify(progress)}::jsonb
   WHERE tenant_id=${scope.tenantId}::uuid AND source_id=${sourceId}::uuid`;
  return {provider:c.provider,historyAccess:c.history_access,scope,sourceId,version:c.version,token,jobId,credentials:c.credentials,url:source.source_url,currency:c.currency,progress:progress as Progress};
 });
}

export async function syncStorePage(scope:StoreScope,sourceId:string){
 let lease:Lease|null;
 try{lease=await claimStorePage(scope,sourceId);}
 catch(error){
  if(!(error instanceof StoreError)||!['STORE_FEATURE_UNAVAILABLE','STORE_SOURCE_LIMIT'].includes(error.code))throw error;
  await storeContext(scope,async tx=>{
   const connection=await lockConnection(tx,scope,sourceId);
   if(connection.job_id)await tx.ingestion_jobs.updateMany({where:{tenant_id:scope.tenantId,job_id:connection.job_id,job_status:'PROCESSING'},data:{job_status:'FAILED',error_log:error.code,ended_at:new Date()}});
   await tx.$executeRaw`UPDATE store_connections SET status='ERROR',last_error=${error.code},lease_token=NULL,lease_until=NULL,job_id=NULL,next_run_at=now()+interval '15 minutes'
    WHERE tenant_id=${scope.tenantId}::uuid AND source_id=${sourceId}::uuid AND status NOT IN ('PAUSED','DISCONNECTED')`;
  },true);
  return {status:'ERROR',code:error.code};
 }
 if(!lease)return {status:'IDLE'};
 try{
  let credentials=openCredentials(lease.credentials,scope.tenantId,sourceId);
  if('provider' in credentials&&credentials.provider==='shopify'&&credentials.expiresAt<Date.now()+120000){
   if(credentials.refreshExpiresAt<=Date.now())throw new StoreError('STORE_RECONNECT_REQUIRED',409);
   credentials=await exchangeShopifyToken(new URL(lease.url).hostname,{grant_type:'refresh_token',refresh_token:credentials.refreshToken},credentials.includeTestOrders);
   const sealed=sealCredentials(credentials,scope.tenantId,sourceId);
   await storeContext(scope,async tx=>{const current=await lockConnection(tx,scope,sourceId);if(current.version!==lease.version||current.lease_token!==lease.token)throw new StoreError('STORE_SYNC_CANCELLED',409);
    await tx.$executeRaw`UPDATE store_connections SET credentials=${sealed} WHERE tenant_id=${scope.tenantId}::uuid AND source_id=${sourceId}::uuid`;});
  }
  if((lease.provider==='shopify')!==('provider' in credentials))throw new StoreError('STORE_CREDENTIALS_UNAVAILABLE');
  const providerCredentials='provider' in credentials?{provider:'shopify',accessToken:credentials.accessToken,includeTestOrders:!!credentials.includeTestOrders}:credentials;
  const response=await storeProvider(scope.tenantId,{action:lease.progress.phase,url:lease.url,...providerCredentials,...(lease.provider==='shopify'?{cursor:lease.progress.cursor??null,historyAccess:lease.historyAccess}:{}),currency:lease.currency,page:lease.progress.page,since:lease.progress.since,until:lease.progress.until,exclude:lease.progress.seen?.map(row=>row.id)||[]});
  if(!response||typeof response!=='object'||!('contractVersion' in response)||![2,3].includes(Number(response.contractVersion)))throw new StoreError('STORE_ADAPTER_UPGRADE_REQUIRED');
  if(Number(response.contractVersion)!==(lease.provider==='shopify'?3:2))throw new StoreError('STORE_ADAPTER_UPGRADE_REQUIRED');
  const page=lease.progress.phase==='products'?productsSchema.parse(response):ordersSchema.parse(response);
  validateProviderPage(lease.provider,lease.progress.phase,page);
  const pageHash=createHash('sha256').update(JSON.stringify(page.items)).digest('hex');
  if(lease.provider==='woocommerce'&&page.hasMore&&lease.progress.lastHash===pageHash)throw new StoreError('STORE_PAGINATION_UNVERIFIED');
  if(new Set(page.items.map(item=>item.externalId)).size!==page.items.length)throw new StoreError('STORE_INVALID_DATA');
  if(lease.progress.phase==='orders'&&(page as ReturnType<typeof ordersSchema.parse>).items.some(order=>new Set(order.lines.map(line=>line.externalId)).size!==order.lines.length))throw new StoreError('STORE_INVALID_DATA');
  let orderCursor:{since:string;seen:Array<{id:string;at:string}>}|null=null;
  if(lease.provider==='shopify'&&page.hasMore&&(!page.nextCursor||page.nextCursor===lease.progress.cursor))throw new StoreError('STORE_PAGINATION_UNVERIFIED');
  if(lease.progress.phase==='orders'){
   const items=(page as ReturnType<typeof ordersSchema.parse>).items;
   const excluded=new Set(lease.progress.seen?.map(row=>row.id)||[]);
   let previous=lease.progress.since?Date.parse(lease.progress.since):-Infinity;
   for(const item of items){const time=Date.parse(item.modifiedAt);if(time<previous||time>Date.parse(lease.progress.until)||excluded.has(item.externalId))throw new StoreError('STORE_PAGINATION_UNVERIFIED');previous=time;}
   if(lease.provider==='woocommerce'&&page.hasMore){
    if(!items.length)throw new StoreError('STORE_PAGINATION_UNVERIFIED');
    const lower=Date.parse(items.at(-1)!.modifiedAt)-1000;
    const seen=[...(lease.progress.seen||[]),...items.map(item=>({id:item.externalId,at:item.modifiedAt}))].filter(item=>Date.parse(item.at)>=lower);
    if(seen.length>250)throw new StoreError('STORE_LIMIT_EXCEEDED');
    orderCursor={since:new Date(lower).toISOString(),seen};
   }
  }
  await storeContext(scope,async tx=>{
   const current=await lockConnection(tx,scope,sourceId);
   const source=await tx.data_sources.findFirst({where:{tenant_id:scope.tenantId,source_id:sourceId,is_active:true,policy_status:'ALLOWED'}});
   if(current.version!==lease.version||current.lease_token!==lease.token||!source||current.status!=='SYNCING')throw new StoreError('STORE_SYNC_CANCELLED',409);
   await lockProductCatalog(tx,scope.tenantId);
   if(lease.progress.phase==='products')for(const item of (page as ReturnType<typeof productsSchema.parse>).items){
    if(lease.provider==='shopify'&&item.active===false){
     const links=await tx.$queryRaw<Array<{product_id:string}>>`SELECT product_id FROM store_product_links WHERE tenant_id=${scope.tenantId}::uuid AND source_id=${sourceId}::uuid AND external_id=${item.externalId}`;
     if(links[0]){await commitStoreLocations(tx,scope,sourceId,links[0].product_id,{...item,locations:[]});
      await tx.$executeRaw`UPDATE products p SET metadata=coalesce(p.metadata,'{}'::jsonb)||jsonb_build_object('store_source_inactive',${sourceId}::text),updated_at=now()
       FROM store_product_links l WHERE l.tenant_id=${scope.tenantId}::uuid AND l.source_id=${sourceId}::uuid AND l.external_id=${item.externalId} AND l.owns_product AND p.tenant_id=l.tenant_id AND p.product_id=l.product_id
       AND NOT EXISTS(SELECT 1 FROM store_product_links other WHERE other.tenant_id=l.tenant_id AND other.product_id=l.product_id AND other.source_id<>l.source_id)`;
     }continue;
    }
    const productId=await linkProduct(tx,lease,item);await auditRow(tx,lease,item,'products',productId);
    if(lease.provider==='shopify'){await commitStoreLocations(tx,scope,sourceId,productId,item);await auditRow(tx,lease,item.locations??[],'products',productId);continue;}
    const inventoryId=await commitStoreInventory(tx,scope,sourceId,productId,item);
    if(inventoryId)await auditRow(tx,lease,item.inventory,'inventory',inventoryId);
   }
   else for(const item of (page as ReturnType<typeof ordersSchema.parse>).items)await commitOrder(tx,lease,item);
   const done=lease.progress.phase==='orders'&&!page.hasMore;
   const progress=done?{}:{...lease.progress,phase:page.hasMore?lease.progress.phase:'orders',page:page.hasMore?lease.progress.page+1:1,lastHash:page.hasMore?pageHash:undefined,cursor:page.hasMore?page.nextCursor??null:null,...(orderCursor||{})};
   if(!done&&(progress as Progress).page>50000)throw new StoreError('STORE_LIMIT_EXCEEDED');
   await tx.$executeRaw`UPDATE store_connections SET status=${done?'CONNECTED':'QUEUED'},lease_token=NULL,lease_until=NULL,attempts=0,last_error=NULL,
    progress=${JSON.stringify(progress)}::jsonb,mapping_version=CASE WHEN ${done} THEN 2 ELSE mapping_version END,job_id=CASE WHEN ${done} THEN NULL ELSE job_id END,last_success_at=CASE WHEN ${done} THEN ${lease.progress.until}::timestamptz ELSE last_success_at END,
    next_run_at=CASE WHEN ${done} AND NOT sync_requested THEN now()+make_interval(mins=>${source.sync_frequency_minutes??60}) ELSE now() END,sync_requested=CASE WHEN ${done} THEN false ELSE sync_requested END
    WHERE tenant_id=${scope.tenantId}::uuid AND source_id=${sourceId}::uuid`;
   const count=await tx.import_staging_rows.count({where:{tenant_id:scope.tenantId,job_id:lease.jobId,validation_status:'COMMITTED'}});
   await tx.ingestion_jobs.updateMany({where:{tenant_id:scope.tenantId,job_id:lease.jobId},data:{rows_processed:count,heartbeat_at:new Date(),...(done?{job_status:'COMPLETED',ended_at:new Date()}: {})}});
   if(done)await tx.data_sources.update({where:{source_id:sourceId},data:{last_synced_at:new Date(lease.progress.until)}});
  });
  return {status:'COMMITTED',phase:lease.progress.phase,page:lease.progress.page};
 }catch(error){
  const code=error instanceof StoreError?error.code:error instanceof ProductError?'STORE_PRODUCT_LIMIT':error instanceof ImportProductError?'STORE_PRODUCT_CONFLICT':'STORE_SYNC_FAILED';
  await storeContext(scope,async tx=>{
   const c=await lockConnection(tx,scope,sourceId);
   if(c.version!==lease.version||c.lease_token!==lease.token)return;
   await tx.$executeRaw`UPDATE store_connections SET status='ERROR',attempts=attempts+1,last_error=${code},lease_token=NULL,lease_until=NULL,job_id=NULL,
    next_run_at=now()+make_interval(secs=>${Math.min(3600,30*2**c.attempts)}) WHERE tenant_id=${scope.tenantId}::uuid AND source_id=${sourceId}::uuid`;
   await tx.ingestion_jobs.updateMany({where:{tenant_id:scope.tenantId,job_id:lease.jobId},data:{job_status:'FAILED',error_log:code,ended_at:new Date()}});
  },true).catch(()=>{});
  return {status:'ERROR',code};
 }
}
