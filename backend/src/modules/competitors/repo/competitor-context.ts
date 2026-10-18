import {prisma} from '../../../config/database.js';
import type {Prisma} from '../../../generated/prisma/client.js';
import {getFeatureAccessInfo} from '../../features/repo/usage.repo.js';
import {CompetitorError,type CompetitorScope} from '../types/competitors.types.js';
const options={maxWait:10000,timeout:30000};
export async function permission(tx: Prisma.TransactionClient, scope: CompetitorScope, key = 'competitors.write') {
  const member=await tx.tenantUser.findFirst({ where:{ tenantId:scope.tenantId,userId:scope.userId,removedAt:null,platformStatus:'active' }, include:{role:true} });
  const permissions=member?.role?.permissions as Record<string,unknown> | undefined;
  return permissions?.all === true || permissions?.[key] === true;
}
export async function context<T>(scope: CompetitorScope, run:(tx:Prisma.TransactionClient, metadata:unknown, canEdit:boolean)=>Promise<T>, write=false, cleanup=false) {
  return prisma.$transaction(async tx => {
    await tx.$queryRaw`SELECT set_config('app.current_tenant_id', ${scope.tenantId}, true), set_config('app.current_user_id', ${scope.userId}, true)`;
    const canEdit=await permission(tx,scope);
    if(write && !canEdit) throw new CompetitorError('FORBIDDEN');
    const access=await getFeatureAccessInfo(scope.tenantId,'competitor_management',tx);
    if(!cleanup) {
      if(!access.subscription) throw new CompetitorError('SUBSCRIPTION_NOT_FOUND');
      if(!access.planFeature) throw new CompetitorError('FORBIDDEN');
    }
    return run(tx,access.planFeature?.metadata,canEdit);
  },options);
}
export async function lock(tx:Prisma.TransactionClient, tenantId:string) {
  await tx.$executeRawUnsafe('SELECT pg_advisory_xact_lock(hashtextextended($1, 0))',`competitors-capacity:${tenantId}`);
}
export async function owned(tx:Prisma.TransactionClient, tenantId:string, id:string) {
  const row=await tx.tenant_competitors.findUnique({where:{tenant_id_global_competitor_id:{tenant_id:tenantId,global_competitor_id:id}},include:{global_competitors:true}});
  if(!row) throw new CompetitorError('RESOURCE_NOT_FOUND'); return row;
}
