import {prisma} from '../../../config/database.js';
import type {Prisma} from '../../../generated/prisma/client.js';
import {getFeatureAccessInfo} from '../../features/repo/usage.repo.js';
import {StoreError,type StoreScope} from './contracts.js';
export const storeTxOptions={maxWait:10000,timeout:60000};
export async function storeContext<T>(scope:StoreScope,fn:(tx:Prisma.TransactionClient)=>Promise<T>,cleanup=false){
 return prisma.$transaction(async tx=>{
  await tx.$queryRaw`SELECT set_config('app.current_tenant_id',${scope.tenantId},true),set_config('app.current_user_id',${scope.userId},true)`;
  const member=await tx.tenantUser.findFirst({where:{tenantId:scope.tenantId,userId:scope.userId,removedAt:null,platformStatus:'active'}});
  if(!member||!['owner','admin'].includes(member.roleKey))throw new StoreError('STORE_FORBIDDEN',403);
  if(!cleanup){
   const companies=await tx.$queryRaw<Array<{tenant_id:string}>>`SELECT tenant_id FROM companies WHERE tenant_id=${scope.tenantId}::uuid AND deleted_at IS NULL AND platform_status='active' AND business_type IS DISTINCT FROM 'platform'`;
   if(!companies.length)throw new StoreError('STORE_FORBIDDEN',403);
   const access=await getFeatureAccessInfo(scope.tenantId,'data_integration',tx);
   if(!access.subscription||!access.planFeature)throw new StoreError('STORE_FEATURE_UNAVAILABLE',403);
  }
  return fn(tx);
 },storeTxOptions);
}
