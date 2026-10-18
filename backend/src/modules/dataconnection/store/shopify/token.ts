import {StoreError} from '../contracts.js';
import {shopDomain,shopifySettings} from './domain.js';
import type {ShopifyCredentials} from '../vault.js';
/** No redirects or arbitrary destinations. Do not include upstream bodies in errors/logs. */
export async function exchangeShopifyToken(shop:string,fields:Record<string,string>,includeTestOrders=false):Promise<ShopifyCredentials>{
 const {clientId,secret}=shopifySettings();
 const url=`https://${shopDomain(shop)}/admin/oauth/access_token`;
 try{
  const response=await fetch(url,{method:'POST',redirect:'error',signal:AbortSignal.timeout(20000),headers:{'Content-Type':'application/json'},body:JSON.stringify({client_id:clientId,client_secret:secret,...fields})});
  const reader=response.body?.getReader();if(!reader)throw Error();let size=0;const chunks:Uint8Array[]=[];
  try{for(;;){const item=await reader.read();if(item.done)break;size+=item.value.length;if(size>65536)throw Error();chunks.push(item.value);}}
  finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
  if(!response.ok)throw new StoreError('STORE_RECONNECT_REQUIRED',409);
  const data=JSON.parse(Buffer.concat(chunks).toString('utf8'));
  if(typeof data.access_token!=='string'||data.access_token.length>4096||typeof data.refresh_token!=='string'||data.refresh_token.length>4096||!Number.isFinite(data.expires_in)||data.expires_in<=0||!Number.isFinite(data.refresh_token_expires_in)||data.refresh_token_expires_in<=0||typeof data.scope!=='string')throw Error();
  const now=Date.now();return {provider:'shopify',accessToken:data.access_token,refreshToken:data.refresh_token,expiresAt:now+data.expires_in*1000,refreshExpiresAt:now+data.refresh_token_expires_in*1000,scopes:data.scope.split(',').map((s:string)=>s.trim()).filter(Boolean),includeTestOrders};
 }catch(error){if(error instanceof StoreError)throw error;throw new StoreError('STORE_SHOPIFY_AUTH_FAILED',503);}
}
