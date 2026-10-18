import type {Prisma} from '../../../generated/prisma/client.js';
import {StoreError,type StoreProduct,type StoreScope} from './contracts.js';

/** A store owns only its reserved location; local warehouses are never merged. */
export async function commitStoreInventory(tx:Prisma.TransactionClient,scope:StoreScope,sourceId:string,productId:string,product:StoreProduct){
 const key={tenant_id:scope.tenantId,source_id:sourceId,external_id:product.externalId};
 const old=await tx.store_inventory_links.findUnique({where:{tenant_id_source_id_external_id:key},include:{inventory:true}});
 const snapshot=product.inventory;
 const known=snapshot.state==='managed'&&snapshot.quantity!==null;
 const warehouse=`WooCommerce:${sourceId}`;
 let inventoryId=old?.inventory_id??null;
 if(known){
  if(old?.inventory&& (old.inventory.product_id!==productId||old.inventory.warehouse_location!==warehouse))throw new StoreError('STORE_INVENTORY_CONFLICT');
  if(!inventoryId){
   // A manually created balance at the reserved location needs review, not adoption.
   if(await tx.inventory.findFirst({where:{tenant_id:scope.tenantId,product_id:productId,warehouse_location:warehouse}}))throw new StoreError('STORE_INVENTORY_CONFLICT');
   inventoryId=(await tx.inventory.create({data:{tenant_id:scope.tenantId,product_id:productId,warehouse_location:warehouse,stock_quantity:snapshot.quantity!,reorder_level:snapshot.lowStockThreshold??0,safety_stock:null}})).inventory_id;
  }else{
   const previousThreshold=old?.low_stock_threshold??0;
   const keepLocalThreshold=old!.inventory!.reorder_level!==previousThreshold;
   await tx.inventory.update({where:{inventory_id:inventoryId},data:{stock_quantity:snapshot.quantity!,...(!keepLocalThreshold?{reorder_level:snapshot.lowStockThreshold??0}:{}),updated_at:new Date()}});
  }
 }else inventoryId=null;
 const data={inventory_id:inventoryId,stock_state:snapshot.state,stock_status:snapshot.stockStatus,low_stock_threshold:snapshot.lowStockThreshold,stock_owner_external_id:snapshot.stockOwnerExternalId,observed_at:new Date()};
 await tx.store_inventory_links.upsert({where:{tenant_id_source_id_external_id:key},create:{...key,...data},update:data});
 // Unknown/unmanaged/shared stock removes only this source's previous numeric
 // balance. It is never represented as zero, including on a later sync.
 if(!known&&old?.inventory_id)await tx.inventory.delete({where:{inventory_id:old.inventory_id}});
 return inventoryId;
}

/** Shopify publishes a complete per-variant location snapshot. Location IDs keep
 * warehouse identities stable when the merchant renames a location. */
export async function commitStoreLocations(tx:Prisma.TransactionClient,scope:StoreScope,sourceId:string,productId:string,product:StoreProduct){
 if(!product.locations)throw new StoreError('STORE_INVALID_DATA');
 if(new Set(product.locations.map(l=>l.externalId)).size!==product.locations.length)throw new StoreError('STORE_INVALID_DATA');
 const old=await tx.$queryRaw<Array<{location_id:string;inventory_id:string|null}>>`SELECT location_id,inventory_id FROM store_inventory_locations WHERE tenant_id=${scope.tenantId}::uuid AND source_id=${sourceId}::uuid AND external_id=${product.externalId}`;
 const kept=new Set(product.locations.map(l=>l.externalId));let count=0;
 for(const location of product.locations){
  const previous=old.find(l=>l.location_id===location.externalId);
  const warehouse=`Shopify:${sourceId}:${location.externalId.split('/').at(-1)}`;
  let id=previous?.inventory_id??null;
  if(location.quantity!==null){
   if(id){
    const balance=await tx.inventory.findFirst({where:{tenant_id:scope.tenantId,inventory_id:id}});
    if(!balance||balance.product_id!==productId||balance.warehouse_location!==warehouse)throw new StoreError('STORE_INVENTORY_CONFLICT');
    await tx.inventory.update({where:{inventory_id:id},data:{stock_quantity:location.quantity,updated_at:new Date()}});
   }else{
    if(await tx.inventory.findFirst({where:{tenant_id:scope.tenantId,product_id:productId,warehouse_location:warehouse}}))throw new StoreError('STORE_INVENTORY_CONFLICT');
    id=(await tx.inventory.create({data:{tenant_id:scope.tenantId,product_id:productId,warehouse_location:warehouse,stock_quantity:location.quantity,reorder_level:0,safety_stock:null}})).inventory_id;
   }
   count++;
  }else id=null;
  await tx.$executeRaw`INSERT INTO store_inventory_locations(tenant_id,source_id,external_id,location_id,inventory_id) VALUES(${scope.tenantId}::uuid,${sourceId}::uuid,${product.externalId},${location.externalId},${id}::uuid)
   ON CONFLICT(tenant_id,source_id,external_id,location_id) DO UPDATE SET inventory_id=EXCLUDED.inventory_id,observed_at=now()`;
  if(previous?.inventory_id&&!id)await tx.inventory.delete({where:{inventory_id:previous.inventory_id}});
 }
 for(const location of old)if(!kept.has(location.location_id)){
  await tx.$executeRaw`DELETE FROM store_inventory_locations WHERE tenant_id=${scope.tenantId}::uuid AND source_id=${sourceId}::uuid AND external_id=${product.externalId} AND location_id=${location.location_id}`;
  if(location.inventory_id)await tx.inventory.delete({where:{inventory_id:location.inventory_id}});
 }
 return count;
}
