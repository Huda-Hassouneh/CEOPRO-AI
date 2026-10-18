import {createHash,randomBytes,randomUUID} from 'node:crypto';
import jwt from 'jsonwebtoken';
import {z} from 'zod';
import {StoreError,type StoreScope} from '../contracts.js';
import {storeContext} from '../context.js';
import {sourceSlot,lockConnection} from '../connections.repo.js';
import {storeProvider} from '../provider.client.js';
import {sealCredentials} from '../vault.js';
import {shopDomain,shopifySettings} from './domain.js';
import {validateShopifyCallback} from './security.js';
import {exchangeShopifyToken} from './token.js';
export const shopifyAuthorizeSchema=z.object({url:z.string().max(2048),sourceId:z.uuid().optional(),consent:z.literal(true),includeTestOrders:z.boolean().default(false),syncFrequencyMinutes:z.number().int().min(15).max(10080).default(60)}).strict();
const requiredScopes=['read_products','read_orders','read_inventory','read_locations'];
const hash=(value:string)=>createHash('sha256').update(value).digest('hex');
const stateSchema=z.object({tenantId:z.uuid(),userId:z.uuid(),shop:z.string(),nonce:z.string().length(64),includeTestOrders:z.boolean()});
export async function beginShopifyAuthorization(scope:StoreScope,input:z.infer<typeof shopifyAuthorizeSchema>){
 const shop=shopDomain(input.url),settings=shopifySettings(),nonce=randomBytes(32).toString('hex');
 const state=jwt.sign({...scope,shop,nonce,includeTestOrders:input.includeTestOrders},settings.secret,{algorithm:'HS256',audience:'keel-shopify-oauth',expiresIn:600});
 await storeContext(scope,async tx=>{
  if(input.sourceId){const c=await lockConnection(tx,scope,input.sourceId);if(c.provider!=='shopify')throw new StoreError('STORE_SOURCE_CONFLICT',409);}
  await sourceSlot(tx,scope,'https://'+shop,input.sourceId);
  await tx.$executeRaw`DELETE FROM store_oauth_states WHERE tenant_id=${scope.tenantId}::uuid AND expires_at<now()`;
  await tx.$executeRaw`INSERT INTO store_oauth_states(tenant_id,user_id,state_hash,shop_domain,source_id,sync_minutes,expires_at) VALUES(${scope.tenantId}::uuid,${scope.userId}::uuid,${hash(state)},${shop},${input.sourceId??null}::uuid,${input.syncFrequencyMinutes},now()+interval '10 minutes')`;
 });
 const url=new URL(`https://${shop}/admin/oauth/authorize`);
 url.search=new URLSearchParams({client_id:settings.clientId,scope:[...requiredScopes,...(process.env.SHOPIFY_REQUEST_ALL_ORDERS==='true'?['read_all_orders']:[])].join(','),redirect_uri:settings.callback,state}).toString();
 return {authorizationUrl:url.href};
}
export async function completeShopifyAuthorization(parameters:URLSearchParams,expectedScope:StoreScope){
 const settings=shopifySettings();validateShopifyCallback(parameters,settings.secret);
 const state=parameters.get('state')??'',code=parameters.get('code')??'',shop=shopDomain(parameters.get('shop')??'');
 let claims:z.infer<typeof stateSchema>;
 try{claims=stateSchema.parse(jwt.verify(state,settings.secret,{algorithms:['HS256'],audience:'keel-shopify-oauth'}));}catch{throw new StoreError('STORE_SHOPIFY_AUTH_EXPIRED');}
 if(claims.shop!==shop||!code||code.length>2048)throw new StoreError('STORE_SHOPIFY_AUTH_FAILED');
 if(expectedScope.tenantId!==claims.tenantId||expectedScope.userId!==claims.userId)throw new StoreError('STORE_FORBIDDEN',403);
 const scope={tenantId:claims.tenantId,userId:claims.userId};
 const pending=await storeContext(scope,async tx=>{
  const rows=await tx.$queryRaw<Array<{source_id:string|null;sync_minutes:number}>>`UPDATE store_oauth_states SET consumed_at=now() WHERE tenant_id=${scope.tenantId}::uuid AND user_id=${scope.userId}::uuid AND state_hash=${hash(state)} AND shop_domain=${shop} AND consumed_at IS NULL AND expires_at>now() RETURNING source_id,sync_minutes`;
  if(!rows[0])throw new StoreError('STORE_SHOPIFY_AUTH_EXPIRED');return rows[0];
 });
 const credentials=await exchangeShopifyToken(shop,{code,expiring:'1'},claims.includeTestOrders);
 const verified=z.object({contractVersion:z.literal(3),verified:z.literal(true),currency:z.string().regex(/^[A-Z]{3}$/),developmentStore:z.boolean(),shopId:z.string().regex(/^gid:\/\/shopify\/Shop\/[1-9][0-9]{0,19}$/),scopes:z.array(z.string()),historyAccess:z.enum(['all','recent'])}).parse(await storeProvider(scope.tenantId,{provider:'shopify',action:'verify',url:'https://'+shop,accessToken:credentials.accessToken}));
 if(!requiredScopes.every(s=>verified.scopes.includes(s)))throw new StoreError('STORE_SHOPIFY_SCOPES_REQUIRED');
 if(claims.includeTestOrders&&!verified.developmentStore)throw new StoreError('STORE_TEST_ORDERS_NOT_ALLOWED',400);
 credentials.scopes=verified.scopes;
 return storeContext(scope,async tx=>{
  await tx.$queryRaw`SELECT pg_advisory_xact_lock(hashtextextended(${'connected-data-sources:'+scope.tenantId},0))::text`;
  const matches=await tx.$queryRaw<Array<{source_id:string}>>`SELECT source_id FROM store_connections WHERE tenant_id=${scope.tenantId}::uuid AND provider='shopify' AND provider_shop_id=${verified.shopId} FOR UPDATE`;
  const existing=await sourceSlot(tx,scope,'https://'+shop,pending.source_id??matches[0]?.source_id);
  const id=pending.source_id??matches[0]?.source_id??existing?.source_id??randomUUID();
  if(existing?.collector_key&&existing.collector_key!=='shopify_node')throw new StoreError('STORE_SOURCE_CONFLICT',409);
  const current=await tx.data_sources.findFirst({where:{tenant_id:scope.tenantId,source_id:id}});
  if(pending.source_id){const c=await lockConnection(tx,scope,id);if(c.provider!=='shopify'||c.provider_shop_id!==verified.shopId)throw new StoreError('STORE_SOURCE_CONFLICT',409);}
  if(current)await tx.$executeRaw`UPDATE ingestion_jobs j SET job_status='FAILED',error_log='STORE_RECONNECTED',ended_at=now() FROM store_connections c WHERE c.tenant_id=${scope.tenantId}::uuid AND c.source_id=${id}::uuid AND j.tenant_id=c.tenant_id AND j.job_id=c.job_id AND j.job_status IN ('PROCESSING','QUEUED')`;
  const data={source_name:shop,source_type:'website',source_url:'https://'+shop,is_active:true,collector_key:'shopify_node',collection_method:'OFFICIAL_API',policy_status:'ALLOWED',sync_frequency_minutes:pending.sync_minutes,approved_by:scope.userId,approved_at:new Date(),privacy_reviewed_at:new Date(),approval_reference:'Shop owner authorized Shopify API access',collection_justification:'Authorized catalog, inventory and operational sales accounting import',collector_config:{provider:'shopify',ceopro_connection_status:'connected',authorized_by:scope.userId,import_test_orders:claims.includeTestOrders}};
  if(current)await tx.data_sources.update({where:{source_id:id},data});else await tx.data_sources.create({data:{...data,tenant_id:scope.tenantId,source_id:id}});
  const sealed=sealCredentials(credentials,scope.tenantId,id),version=randomUUID();
  await tx.$executeRaw`INSERT INTO store_connections(tenant_id,source_id,actor_id,credentials,currency,version,provider,shop_domain,provider_shop_id,history_access) VALUES(${scope.tenantId}::uuid,${id}::uuid,${scope.userId}::uuid,${sealed},${verified.currency},${version}::uuid,'shopify',${shop},${verified.shopId},${verified.historyAccess})
   ON CONFLICT(tenant_id,source_id) DO UPDATE SET actor_id=EXCLUDED.actor_id,credentials=EXCLUDED.credentials,currency=EXCLUDED.currency,version=EXCLUDED.version,provider='shopify',shop_domain=EXCLUDED.shop_domain,provider_shop_id=EXCLUDED.provider_shop_id,mapping_version=CASE WHEN store_connections.history_access='recent' AND EXCLUDED.history_access='all' THEN 1 ELSE store_connections.mapping_version END,history_access=EXCLUDED.history_access,status='QUEUED',next_run_at=now(),last_error=NULL,lease_token=NULL,lease_until=NULL,attempts=0,progress='{}',job_id=NULL`;
  await tx.audit_logs.create({data:{tenant_id:scope.tenantId,user_id:scope.userId,action_type:'STORE_CONNECTED',target_table:'data_sources',record_id:id,changed_data_json:{provider:'shopify',url:'https://'+shop,historyAccess:verified.historyAccess,importTestOrders:claims.includeTestOrders}}});
  return {id,connectionStatus:'connected'};
 });
}

/** The unauthenticated callback never stores tokens. Finish only in the initiating
 * KEEL browser/account, using a short-lived server-signed callback ticket. */
export function createShopifyCallbackTicket(parameters:URLSearchParams){
 const {secret}=shopifySettings();validateShopifyCallback(parameters,secret);
 const state=parameters.get('state')??'';
 try{const claims=stateSchema.parse(jwt.verify(state,secret,{algorithms:['HS256'],audience:'keel-shopify-oauth'}));if(claims.shop!==shopDomain(parameters.get('shop')??'')||!parameters.get('code'))throw Error();}
 catch{throw new StoreError('STORE_SHOPIFY_AUTH_EXPIRED');}
 return {state,ticket:jwt.sign({callback:parameters.toString()},secret,{algorithm:'HS256',audience:'keel-shopify-finish',expiresIn:120})};
}
export async function finishShopifyTicket(scope:StoreScope,ticket:string){
 let callback:string;
 try{const result=jwt.verify(ticket,shopifySettings().secret,{algorithms:['HS256'],audience:'keel-shopify-finish'});callback=z.object({callback:z.string().max(12000)}).parse(result).callback;}
 catch{throw new StoreError('STORE_SHOPIFY_AUTH_EXPIRED');}
 return completeShopifyAuthorization(new URLSearchParams(callback),scope);
}
