import {randomUUID} from 'node:crypto';
import {z} from 'zod';
import {storeContext} from './context.js';
import {StoreError,storeUrl,connectSchema,type StoreScope} from './contracts.js';
import {storeProvider} from './provider.client.js';
import {sealCredentials} from './vault.js';
import {getConnectedDataSourceCapacityInTransaction} from '../../features/repo/usage.repo.js';
import type {Prisma} from '../../../generated/prisma/client.js';
export type Connection={provider:'woocommerce'|'shopify';shop_domain:string|null;provider_shop_id:string|null;history_access:string;sync_requested:boolean;tenant_id:string;source_id:string;actor_id:string;version:string;credentials:string|null;currency:string;status:string;progress:unknown;lease_token:string|null;lease_until:Date|null;attempts:number;job_id:string|null;last_success_at:Date|null;last_error:string|null;next_run_at:Date;mapping_version:number};
export async function lockConnection(tx:Prisma.TransactionClient,scope:StoreScope,sourceId:string):Promise<Connection>{
 await tx.$queryRaw`SELECT source_id FROM data_sources WHERE tenant_id=${scope.tenantId}::uuid AND source_id=${sourceId}::uuid FOR UPDATE`;
 const rows=await tx.$queryRaw<Connection[]>`SELECT * FROM store_connections WHERE tenant_id=${scope.tenantId}::uuid AND source_id=${sourceId}::uuid FOR UPDATE`;
 if(!rows[0])throw new StoreError('STORE_NOT_FOUND',404);return rows[0];
}
export async function sourceSlot(tx:Prisma.TransactionClient,scope:StoreScope,url:string,existingId?:string){
 const existing=await tx.data_sources.findFirst({where:{tenant_id:scope.tenantId,source_type:'website',...(existingId?{source_id:existingId}:{source_url:url})},orderBy:{created_at:'asc'}});
 if(existing?.collector_key&&!['woocommerce_node','shopify_node'].includes(existing.collector_key))throw new StoreError('STORE_SOURCE_CONFLICT',409);
 const capacity=await getConnectedDataSourceCapacityInTransaction(tx,scope.tenantId);
 if(!capacity.included||!capacity.isUnlimited&&(existing?.is_active?capacity.currentUsage>(capacity.limit??0):(capacity.remaining??0)<1))throw new StoreError('STORE_SOURCE_LIMIT',402);
 return existing;
}
export const storeConnections={
 detect:async(scope:StoreScope,url:string)=>{
  await storeContext(scope,async()=>{});
  const normalized=storeUrl(url);
  const {shopDomain}=await import('./shopify/domain.js');
  if(new URL(normalized).hostname.endsWith('.myshopify.com'))return {supported:true,provider:'shopify',url:'https://'+shopDomain(normalized)};
  const result=z.object({supported:z.boolean(),provider:z.literal('woocommerce'),url:z.string()}).parse(await storeProvider(scope.tenantId,{action:'detect',url:normalized}));
  return {...result,url:normalized};
 },
 connect:async(scope:StoreScope,input:z.infer<typeof connectSchema>)=>{
  const url=storeUrl(input.url);
  await storeContext(scope,tx=>sourceSlot(tx,scope,url));
  const response=await storeProvider(scope.tenantId,{action:'verify',url,key:input.consumerKey,secret:input.consumerSecret});
  if(!response||typeof response!=='object'||!('contractVersion' in response)||response.contractVersion!==2)throw new StoreError('STORE_ADAPTER_UPGRADE_REQUIRED',503);
  const verified=z.object({contractVersion:z.literal(2),verified:z.literal(true),currency:z.string().regex(/^[A-Z]{3}$/)}).passthrough().parse(response);
  return storeContext(scope,async tx=>{
   await tx.$executeRawUnsafe('SELECT pg_advisory_xact_lock(hashtextextended($1,0))','connected-data-sources:'+scope.tenantId);
   const existing=await sourceSlot(tx,scope,url);
   const sourceId=existing?.source_id??randomUUID(),version=randomUUID();
   if(existing?.collector_key==='shopify_node')throw new StoreError('STORE_SOURCE_CONFLICT',409);
   const credentials=sealCredentials({key:input.consumerKey,secret:input.consumerSecret},scope.tenantId,sourceId);
   const data={source_name:new URL(url).hostname,source_type:'website',source_url:url,is_active:true,collector_key:'woocommerce_node',
    collection_method:'OFFICIAL_API',policy_status:'ALLOWED',sync_frequency_minutes:input.syncFrequencyMinutes,
    approved_by:scope.userId,approved_at:new Date(),privacy_reviewed_at:new Date(),
    approval_reference:'Owner-authorized WooCommerce read-only API; credentials verified',
    collection_justification:'Authorized import of products, managed stock, sales and order invoices; customer identity fields excluded',
    collector_config:{provider:'woocommerce',ceopro_connection_status:'connected',authorized_by:scope.userId}};
   if(existing){
    await tx.$queryRaw`SELECT source_id FROM data_sources WHERE tenant_id=${scope.tenantId}::uuid AND source_id=${sourceId}::uuid FOR UPDATE`;
    await tx.$executeRaw`UPDATE ingestion_jobs j SET job_status='FAILED',error_log='STORE_RECONNECTED',ended_at=now() FROM store_connections c
     WHERE c.tenant_id=${scope.tenantId}::uuid AND c.source_id=${sourceId}::uuid AND j.tenant_id=c.tenant_id AND j.job_id=c.job_id AND j.job_status IN ('PROCESSING','QUEUED')`;
    await tx.data_sources.update({where:{source_id:sourceId},data});
   }
   else await tx.data_sources.create({data:{...data,tenant_id:scope.tenantId,source_id:sourceId}});
   await tx.$executeRaw`INSERT INTO store_connections(tenant_id,source_id,actor_id,credentials,currency,version)
    VALUES(${scope.tenantId}::uuid,${sourceId}::uuid,${scope.userId}::uuid,${credentials},${verified.currency},${version}::uuid)
    ON CONFLICT(tenant_id,source_id) DO UPDATE SET actor_id=EXCLUDED.actor_id,credentials=EXCLUDED.credentials,currency=EXCLUDED.currency,version=EXCLUDED.version,
     status='QUEUED',next_run_at=now(),last_error=NULL,lease_token=NULL,lease_until=NULL,attempts=0,progress='{}',job_id=NULL`;
   await tx.audit_logs.create({data:{tenant_id:scope.tenantId,user_id:scope.userId,action_type:'STORE_CONNECTED',target_table:'data_sources',record_id:sourceId,changed_data_json:{provider:'woocommerce',url}}});
   return {id:sourceId,sourceUrl:url,connectionStatus:'connected',syncStatus:'QUEUED',isActive:true};
  });
 },
 status:(scope:StoreScope,id:string)=>storeContext(scope,async tx=>{
  const rows=await tx.$queryRaw`SELECT source_id,status,last_success_at,last_error,next_run_at,job_id FROM store_connections WHERE tenant_id=${scope.tenantId}::uuid AND source_id=${id}::uuid`;
  if(!(rows as unknown[]).length)throw new StoreError('STORE_NOT_FOUND',404);
  return rows;
 },true),
 sync:(scope:StoreScope,id:string)=>storeContext(scope,async tx=>{
  const connection=await lockConnection(tx,scope,id);
  const source=await tx.data_sources.findFirst({where:{tenant_id:scope.tenantId,source_id:id,is_active:true}});
  if(!source||!connection.credentials||connection.status==='DISCONNECTED')throw new StoreError('STORE_RECONNECT_REQUIRED',409);
  if(connection.lease_until&&connection.lease_until>new Date()){await tx.$executeRaw`UPDATE store_connections SET sync_requested=true WHERE tenant_id=${scope.tenantId}::uuid AND source_id=${id}::uuid`;return {queued:false,status:'SYNCING'};}
  await tx.$executeRaw`UPDATE store_connections SET status='QUEUED',next_run_at=now(),attempts=0 WHERE tenant_id=${scope.tenantId}::uuid AND source_id=${id}::uuid`;
  return {queued:true,status:'QUEUED'};
 }),
 disconnect:(scope:StoreScope,id:string)=>storeContext(scope,async tx=>{
  const connection=await lockConnection(tx,scope,id);
  await tx.data_sources.updateMany({where:{tenant_id:scope.tenantId,source_id:id},data:{is_active:false,connection_credentials_vault:null,collector_config:{provider:'woocommerce',ceopro_connection_status:'disconnected'}}});
  if(connection.job_id)await tx.ingestion_jobs.updateMany({where:{tenant_id:scope.tenantId,job_id:connection.job_id,job_status:{in:['PROCESSING','QUEUED']}},data:{job_status:'FAILED',error_log:'STORE_DISCONNECTED',ended_at:new Date()}});
  return {id,connectionStatus:'disconnected',isActive:false};
 },true)
};
