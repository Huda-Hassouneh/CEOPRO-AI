import {Router} from 'express';
import type {NextFunction,Response} from 'express';
import {z} from 'zod';
import type {AppRequest} from '../../../types/request.js';
import {storeConnections} from './connections.repo.js';
import {StoreError,connectSchema,detectSchema} from './contracts.js';
import {storeContext} from './context.js';
import {prisma} from '../../../config/database.js';
const router=Router();
router.use((_req,res,next)=>{res.setHeader('Cache-Control','no-store');next();});
const handle=(action:(req:AppRequest)=>Promise<unknown>)=>async(req:AppRequest,res:Response)=>{
 try{res.json({success:true,message:'OK',data:await action(req)});}
 catch(error){const issue=error instanceof StoreError?error:new StoreError(error instanceof z.ZodError?'STORE_INVALID_REQUEST':'STORE_SERVICE_UNAVAILABLE',error instanceof z.ZodError?400:503);
  res.status(issue.status).json({success:false,message:issue.code,code:issue.code,statusCode:issue.status});}
};
const scope=(req:AppRequest)=>{if(!req.tenant_id||!req.user?.id)throw new StoreError('STORE_FORBIDDEN',403);return {tenantId:req.tenant_id,userId:req.user.id};};
const source=(req:AppRequest)=>z.uuid().parse(req.params.sourceId);
export async function protectStoreLifecycle(req:AppRequest,res:Response,next:NextFunction){
 try{
  const id=z.uuid().safeParse(req.params.sourceId);if(!id.success){next();return;}
  const s=scope(req);
  const store=await prisma.$transaction(async tx=>{
   await tx.$queryRaw`SELECT set_config('app.current_tenant_id',${s.tenantId},true),set_config('app.current_user_id',${s.userId},true)`;
   return tx.data_sources.findFirst({where:{tenant_id:s.tenantId,source_id:id.data,collector_key:{in:['woocommerce_node','shopify_node']}},select:{source_id:true}});
  });
  if(store)await storeContext(s,async()=>{},true);
  next();
 }catch(error){const issue=error instanceof StoreError?error:new StoreError('STORE_SERVICE_UNAVAILABLE',503);res.status(issue.status).json({success:false,code:issue.code,message:issue.code,statusCode:issue.status});}
}
router.post('/shopify/complete',handle(async req=>{const {finishShopifyTicket}=await import('./shopify/oauth.js');const body=z.object({ticket:z.string().max(20000)}).strict().parse(req.body);return finishShopifyTicket(scope(req),body.ticket);}));
router.post('/shopify/authorize',handle(async req=>{const {beginShopifyAuthorization,shopifyAuthorizeSchema}=await import('./shopify/oauth.js');return beginShopifyAuthorization(scope(req),shopifyAuthorizeSchema.parse(req.body));}));
router.post('/detect',handle(req=>storeConnections.detect(scope(req),detectSchema.parse(req.body).url)));
router.post('/connect',handle(req=>storeConnections.connect(scope(req),connectSchema.parse(req.body))));
router.get('/:sourceId/privacy-reports',handle(req=>storeContext(scope(req),tx=>tx.$queryRaw`SELECT event_id,created_at,report FROM shopify_privacy_reports WHERE tenant_id=${scope(req).tenantId}::uuid AND source_id=${source(req)}::uuid ORDER BY created_at DESC LIMIT 100`,true)));
router.get('/:sourceId',handle(req=>storeConnections.status(scope(req),source(req))));
router.post('/:sourceId/sync',handle(req=>storeConnections.sync(scope(req),source(req))));
router.delete('/:sourceId',handle(req=>storeConnections.disconnect(scope(req),source(req))));
export default router;
