import {Router,type Response,type NextFunction} from 'express';
import {z} from 'zod';
import {authenticateUser,requireTenant} from '../../middleware/validators/validateUser.js';
import {requireFeatureAccess} from '../../middleware/validators/validateFeatures.js';
import type {AppRequest} from '../../types/request.js';
import {errorResponse,successResponse} from '../../types/response.js';
import * as service from './service.js';
const router=Router();
export function insightPermission(req:AppRequest,res:Response,next:NextFunction){
 const p=req.tenantUser?.role?.permissions as Record<string,unknown>|undefined;
 if(!p||!['all','view_analytics','manage_catalog'].some(k=>p[k]===true)){res.status(403).json(errorResponse('Permission denied',403,'FORBIDDEN'));return;}
 next();
}
router.use(authenticateUser,requireTenant,requireFeatureAccess('business_recommendations'),insightPermission);
const scope=(req:AppRequest)=>({tenantId:req.tenant_id!,userId:req.user!.user_id??req.user!.id});
function handle(error:unknown,res:Response){
 if(error instanceof service.RecommendationError){const status=error.code==='FEATURE_NOT_INCLUDED'?403:error.code==='NOT_FOUND'?404:409;
  res.status(status).json(errorResponse('Recommendation request could not be completed',status,'BUSINESS_'+error.code,{reason:error.code}));return;}
 console.error('[BusinessRecommendations]',error instanceof Error?error.message:'Unknown failure');
 res.status(503).json(errorResponse('The business insight service is unavailable',503,'SERVICE_UNAVAILABLE',{reason:'INSIGHTS_SERVICE_UNAVAILABLE'}));
}
router.get('/',async(req:AppRequest,res)=>{const q=z.object({state:z.enum(['active','dismissed','resolved','all']).default('active'),page:z.coerce.number().int().min(1).max(10000).default(1)}).safeParse(req.query);
 if(!q.success){res.status(400).json(errorResponse('Invalid query',400,'VALIDATION_ERROR'));return;}
 try{const data=await service.listRecommendations(scope(req),q.data.state,q.data.page);const p=req.tenantUser?.role?.permissions as Record<string,unknown>;res.json(successResponse({...data,can_manage:p.all===true||p.manage_catalog===true},'Recommendations'));}catch(e){handle(e,res);}});
router.post('/refresh',async(req:AppRequest,res)=>{const q=z.object({request_id:z.uuid()}).safeParse(req.body);
 if(!q.success){res.status(400).json(errorResponse('A request UUID is required',400,'VALIDATION_ERROR'));return;}
 try{res.json(successResponse(await service.refreshRecommendations(scope(req),q.data.request_id,req.headers.authorization!),'Recommendations refreshed'));}catch(e){handle(e,res);}});
router.patch('/:id/state',async(req:AppRequest,res)=>{const p=req.tenantUser?.role?.permissions as Record<string,unknown>;if(p.all!==true&&p.manage_catalog!==true){res.status(403).json(errorResponse('Permission denied',403,'FORBIDDEN'));return;}const q=z.object({state:z.enum(['active','dismissed'])}).safeParse(req.body);
 if(!q.success||!z.uuid().safeParse(req.params.id).success){res.status(400).json(errorResponse('Invalid recommendation',400,'VALIDATION_ERROR'));return;}
 try{res.json(successResponse(await service.setRecommendationState(scope(req),String(req.params.id),q.data.state),'Recommendation updated'));}catch(e){handle(e,res);}});
router.get('/:id/evidence',async(req:AppRequest,res)=>{if(!z.uuid().safeParse(req.params.id).success){res.status(404).json(errorResponse('Not found',404,'RESOURCE_NOT_FOUND'));return;}
 try{res.json(successResponse(await service.recommendationEvidence(scope(req),String(req.params.id)),'Recommendation evidence'));}catch(e){handle(e,res);}});
export default router;
