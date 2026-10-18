import {z} from 'zod';
import {normalizeSourceUrl} from '../types/source-url.js';
export type StoreScope={tenantId:string;userId:string};
export class StoreError extends Error {
 constructor(readonly code:string,readonly status=400){super(code);}
}
export function storeUrl(value:unknown){
 if(typeof value!=='string'||/%|\\/.test(value))throw new StoreError('INVALID_STORE_URL');
 const normalized=normalizeSourceUrl(value);
 if(!normalized.success||!normalized.data)throw new StoreError('INVALID_STORE_URL');
 const url=new URL(normalized.data);
 if(url.protocol!=='https:'||url.search||url.hash||url.port||/%|\\/.test(url.pathname))throw new StoreError('INVALID_STORE_URL');
 return normalized.data;
}
export const detectSchema=z.object({url:z.string().max(2048)}).strict();
export const connectSchema=detectSchema.extend({consumerKey:z.string().regex(/^ck_[a-fA-F0-9]{40}$/),consumerSecret:z.string().regex(/^cs_[a-fA-F0-9]{40}$/),
 consent:z.literal(true),syncFrequencyMinutes:z.number().int().min(15).max(10080).default(60)}).strict();
export const externalId=z.string().regex(/^(?:[1-9][0-9]{0,18}|gid:\/\/shopify\/(?:ProductVariant|Order|LineItem|Location|Shop)\/[1-9][0-9]{0,19})$/);
const id=externalId;
const money=z.string().regex(/^\d{1,8}(?:\.\d{1,4})?$/);
export const inventorySchema=z.object({state:z.enum(['managed','unmanaged','shared']),quantity:z.number().int().min(0).max(2147483647).nullable(),stockStatus:z.enum(['instock','outofstock','onbackorder']).nullable(),lowStockThreshold:z.number().int().min(0).max(2147483647).nullable(),stockOwnerExternalId:id.nullable()}).strict().refine(value=>value.state==='managed'||value.quantity===null);
export const productSchema=z.object({externalId:id,name:z.string().min(1).max(500),sku:z.string().regex(/^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/).nullable(),price:money,currency:z.string().regex(/^[A-Z]{3}$/),inventory:inventorySchema,active:z.boolean().optional(),parentExternalId:z.string().regex(/^gid:\/\/shopify\/Product\/[1-9][0-9]{0,19}$/).optional(),gtin:z.string().regex(/^(?:\d{8}|\d{12}|\d{13}|\d{14})$/).nullable().optional(),locations:z.array(z.object({externalId:id,quantity:z.number().int().min(0).max(2147483647).nullable()}).strict()).max(500).optional()}).strict();
export const saleSchema=z.object({externalId:id,productExternalId:id,name:z.string().min(1).max(500),sku:z.string().regex(/^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/).nullable(),quantity:z.number().int().positive().max(999999999),unitPrice:money,total:money,currency:z.string().regex(/^[A-Z]{3}$/),date:z.iso.datetime({offset:true})}).strict();
export const invoiceSchema=z.object({currency:z.string().regex(/^[A-Z]{3}$/),issuedAt:z.iso.datetime({offset:true}),paidAt:z.iso.datetime({offset:true}).nullable(),paymentStatus:z.enum(['PAID','UNPAID','PARTIAL','CANCELLED']),subtotal:money,tax:money,total:money,merchandise:money,shipping:money,fees:money,discount:money,originalTotal:money,refundedTotal:money,items:z.array(saleSchema).max(500)}).strict();
export const ordersSchema=z.object({contractVersion:z.union([z.literal(2),z.literal(3)]),items:z.array(z.object({externalId:id,modifiedAt:z.iso.datetime({offset:true}),status:z.enum(['pending','processing','on-hold','completed','cancelled','refunded','failed','trash','open','closed']),invoice:invoiceSchema,lines:z.array(saleSchema).max(500),salesEligible:z.boolean().optional(),financialStatus:z.string().max(40).optional()}).strict()).max(20),hasMore:z.boolean(),nextCursor:z.string().max(4096).nullable().optional()}).strict();
export const productsSchema=z.object({contractVersion:z.union([z.literal(2),z.literal(3)]),items:z.array(productSchema).max(500),hasMore:z.boolean(),nextCursor:z.string().max(4096).nullable().optional()}).strict();
export type StoreProduct=z.infer<typeof productSchema>;
export type StoreOrder=z.infer<typeof ordersSchema>['items'][number];

export type StoreProvider='woocommerce'|'shopify';
export const storeCollector=(provider:StoreProvider)=>provider==='shopify'?'shopify_node':'woocommerce_node';
export const storeCollectors=['woocommerce_node','shopify_node'];
