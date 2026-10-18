import {randomUUID} from 'node:crypto';
import {Prisma} from '../../../generated/prisma/client.js';
import {StoreError,type StoreOrder,type StoreScope} from './contracts.js';

type OrderLine=StoreOrder['invoice']['items'][number];
const decimal=(value:string)=>new Prisma.Decimal(value);

/** Recheck provider accounting before any invoice or sales write. */
export function validateStoreOrder(order:StoreOrder){
 const i=order.invoice;
 const sum=i.items.reduce((total,line)=>total.plus(line.total),decimal('0'));
 const expectedCancelled=['cancelled','failed','trash','refunded'].includes(order.status)||decimal(i.refundedTotal).gt(0)&&decimal(i.total).isZero();
 const shopify=order.salesEligible!==undefined;
 const expectedStatus=expectedCancelled?'CANCELLED':shopify?(order.financialStatus==='PARTIALLY_PAID'?'PARTIAL':['PAID','PARTIALLY_REFUNDED'].includes(order.financialStatus??'')?'PAID':'UNPAID'):i.paidAt?'PAID':'UNPAID';
 const expectedSales=(shopify?order.salesEligible&&expectedStatus==='PAID':order.status==='completed')&&!expectedCancelled?i.items:[];
 if(shopify&&(order.salesEligible!==(!expectedCancelled&&expectedStatus==='PAID')||expectedStatus==='PAID'&&!i.paidAt))throw new StoreError('STORE_ORDER_TOTAL_MISMATCH');
 if(i.paymentStatus!==expectedStatus||!sum.equals(i.merchandise)||
  !decimal(i.subtotal).equals(sum.plus(i.shipping).plus(i.fees))||
  !decimal(i.total).equals(decimal(i.subtotal).plus(i.tax))||
  !decimal(i.originalTotal).equals(decimal(i.total).plus(i.refundedTotal))||
  new Set(i.items.map(line=>line.externalId)).size!==i.items.length||
  JSON.stringify(order.lines)!==JSON.stringify(expectedSales)||
  order.status==='refunded'&&!decimal(i.total).isZero()||
  i.items.some(line=>line.currency!==i.currency||decimal(line.total).minus(decimal(line.unitPrice).times(line.quantity)).abs().gt(decimal('0.00005').times(line.quantity)))){
  throw new StoreError('STORE_ORDER_TOTAL_MISMATCH');
 }
}

export async function commitStoreInvoice(tx:Prisma.TransactionClient,scope:StoreScope,sourceId:string,order:StoreOrder,resolveProduct:(line:OrderLine)=>Promise<string>,provider:'woocommerce'|'shopify'='woocommerce'){
 const key={tenant_id:scope.tenantId,source_id:sourceId,order_id:order.externalId};
 const before=await tx.store_order_links.findUnique({where:{tenant_id_source_id_order_id:key},include:{items:true}});
 const invoice=order.invoice,invoiceId=before?.invoice_id??randomUUID();
 const values={subtotal:invoice.subtotal,tax_amount:invoice.tax,total_amount:invoice.total,currency:invoice.currency,
  payment_status:invoice.paymentStatus,issue_date:new Date(invoice.issuedAt),updated_at:new Date()};
 if(before)await tx.invoices.update({where:{invoice_id:invoiceId},data:values});
 else await tx.invoices.create({data:{...values,tenant_id:scope.tenantId,invoice_id:invoiceId,
  invoice_number:`${provider==='shopify'?'SH':'WC'}-${sourceId}-${order.externalId.split('/').at(-1)}`,created_by_user_id:scope.userId}});
 const {items:_,...accounting}=invoice;
 if(order.financialStatus)Object.assign(accounting,{financialStatus:order.financialStatus});
 await tx.store_order_links.upsert({where:{tenant_id_source_id_order_id:key},create:{...key,invoice_id:invoiceId,
  order_status:order.status,source_modified_at:new Date(order.modifiedAt),paid_at:invoice.paidAt?new Date(invoice.paidAt):null,accounting},
  update:{order_status:order.status,source_modified_at:new Date(order.modifiedAt),paid_at:invoice.paidAt?new Date(invoice.paidAt):null,accounting}});
 const retained=new Set(invoice.items.map(line=>line.externalId));
 for(const old of before?.items??[])if(!retained.has(old.line_id)){
  await tx.store_order_item_links.delete({where:{tenant_id_source_id_order_id_line_id:{...key,line_id:old.line_id}}});
  await tx.invoice_items.delete({where:{invoice_item_id:old.invoice_item_id}});
 }
 for(const line of invoice.items){
  const old=before?.items.find(row=>row.line_id===line.externalId),itemId=old?.invoice_item_id??randomUUID();
  const data={product_id:await resolveProduct(line),quantity:line.quantity,unit_price:line.unitPrice,total_price:line.total,
   rounding_adjustment:decimal(line.total).minus(decimal(line.unitPrice).times(line.quantity))};
  if(old)await tx.invoice_items.update({where:{invoice_item_id:itemId},data});
  else{
   await tx.invoice_items.create({data:{...data,tenant_id:scope.tenantId,invoice_id:invoiceId,invoice_item_id:itemId}});
   await tx.store_order_item_links.create({data:{...key,line_id:line.externalId,invoice_id:invoiceId,invoice_item_id:itemId}});
  }
 }
 return invoiceId;
}
