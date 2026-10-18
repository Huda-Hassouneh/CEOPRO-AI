import {StoreError,type StoreProvider,productsSchema,ordersSchema} from './contracts.js';
/** Do not allow a payload to switch provider semantics inside a source lease. */
export function validateProviderPage(provider:StoreProvider,phase:'products'|'orders',page:ReturnType<typeof productsSchema.parse>|ReturnType<typeof ordersSchema.parse>){
 const id=(value:string,kind:string)=>provider==='shopify'?new RegExp(`^gid://shopify/${kind}/[1-9][0-9]{0,19}$`).test(value):/^[1-9][0-9]{0,18}$/.test(value);
 for(const raw of page.items){
  if(!id(raw.externalId,phase==='products'?'ProductVariant':'Order'))throw new StoreError('STORE_INVALID_DATA');
  if(phase==='products'){
   const p=raw as ReturnType<typeof productsSchema.parse>['items'][number];
   if(provider==='shopify'&&(typeof p.active!=='boolean'||!p.parentExternalId||!p.locations||p.locations.some(l=>!id(l.externalId,'Location')))||provider==='woocommerce'&&p.locations)throw new StoreError('STORE_INVALID_DATA');
  }else{
   const o=raw as ReturnType<typeof ordersSchema.parse>['items'][number];
   if(provider==='shopify'&&(typeof o.salesEligible!=='boolean'||!o.financialStatus||!['open','closed','cancelled'].includes(o.status))||provider==='woocommerce'&&o.salesEligible!==undefined)throw new StoreError('STORE_INVALID_DATA');
   if(o.invoice.items.some(l=>!id(l.externalId,'LineItem')||!id(l.productExternalId,'ProductVariant')))throw new StoreError('STORE_INVALID_DATA');
  }
 }
}
