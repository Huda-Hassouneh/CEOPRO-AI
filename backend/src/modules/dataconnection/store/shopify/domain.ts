import {StoreError} from '../contracts.js';
/** Only Shopify's canonical shop host is accepted; custom storefront domains are not API identities. */
export function shopDomain(value:string){
 let host=value.trim().toLowerCase();
 if(host.startsWith('https://')){
  const url=new URL(host);
  if(url.username||url.password||url.port||url.search||url.hash||!['','/'].includes(url.pathname))throw new StoreError('STORE_INVALID_SHOPIFY_DOMAIN');
  host=url.hostname;
 }
 if(!/^[a-z0-9][a-z0-9-]{0,62}\.myshopify\.com$/.test(host))throw new StoreError('STORE_INVALID_SHOPIFY_DOMAIN');
 return host;
}
export function shopifySettings(){
 const clientId=process.env.SHOPIFY_CLIENT_ID?.trim(),secret=process.env.SHOPIFY_CLIENT_SECRET?.trim();
 const callback=process.env.SHOPIFY_REDIRECT_URI?.trim(),frontend=process.env.FRONTEND_URL?.trim();
 if(!clientId||!secret||!callback||!frontend)throw new StoreError('STORE_SHOPIFY_NOT_CONFIGURED',503);
 for(const [value,localAllowed] of [[callback,false],[frontend,true]] as const){
  const url=new URL(value);
  if(url.username||url.password||url.hash||url.search||url.protocol!=='https:'&&!(localAllowed&&url.protocol==='http:'&&['localhost','127.0.0.1'].includes(url.hostname)))throw new StoreError('STORE_SHOPIFY_NOT_CONFIGURED',503);
 }
 return {clientId,secret,callback,frontend};
}
