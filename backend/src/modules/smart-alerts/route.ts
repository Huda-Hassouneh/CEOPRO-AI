import {COMPETITOR_AI_ACTIONS_ENABLED} from '../competitors/service/competitor-capabilities.js';
import {sendApiError} from '../../utils/http.js';
import {Router} from 'express';
import {z} from 'zod';
import {prisma} from '../../config/database.js';
import type {Prisma} from '../../generated/prisma/client.js';
import type {AppRequest} from '../../types/request.js';
import {authenticateUser,requireTenant} from '../../middleware/validators/validateUser.js';
import {requireFeatureAccess} from '../../middleware/validators/validateFeatures.js';
import {insightPermission} from '../business-recommendations/route.js';
const router=Router();
router.use(authenticateUser,requireTenant,requireFeatureAccess('system_alerts'),insightPermission);
router.use((_req,res,next)=>{if(!COMPETITOR_AI_ACTIONS_ENABLED){sendApiError(res,'NOT_IMPLEMENTED');return;}next();});
const permissions=(req:AppRequest)=>req.tenantUser?.role?.permissions as Record<string,unknown>;
async function scoped<T>(req:AppRequest,fn:(tx:Prisma.TransactionClient)=>Promise<T>){return prisma.$transaction(async tx=>{
 await tx.$queryRaw`SELECT set_config('app.current_tenant_id',${req.tenant_id!},true),set_config('app.current_user_id',${req.user!.user_id??req.user!.id},true)`;
 return fn(tx);
});}
const rule=z.object({name:z.string().trim().min(1).max(120),global_competitor_id:z.uuid(),operator:z.enum(['GT','GTE','LT','LTE']),threshold:z.number().finite().min(-100).max(10000),cooldown_minutes:z.number().int().min(0).max(10080).default(60),is_active:z.boolean().default(true)}).strict();
router.get('/',async(req:AppRequest,res,next)=>{try{
 const parsed=z.object({state:z.enum(['open','acknowledged','resolved','all']).default('open'),page:z.coerce.number().int().min(1).max(10000).default(1)}).safeParse(req.query);
 if(!parsed.success){res.status(400).json({message:'Invalid alert query'});return;}
 const {state,page}=parsed.data;const data=await scoped(req,async tx=>{
 const where={tenant_id:req.tenant_id!,...(state==='open'?{acknowledged_at:null,resolved_at:null}:state==='acknowledged'?{acknowledged_at:{not:null},resolved_at:null}:state==='resolved'?{resolved_at:{not:null}}:{})};
 const [events,total,rules,competitors]=await Promise.all([
 tx.market_alert_events.findMany({where,include:{market_alert_rules:true,market_events:true},orderBy:[{created_at:'desc'},{alert_event_id:'desc'}],skip:(page-1)*20,take:20}),
 tx.market_alert_events.count({where}),tx.market_alert_rules.findMany({where:{tenant_id:req.tenant_id!},orderBy:{created_at:'desc'}}),
 tx.tenant_competitors.findMany({where:{tenant_id:req.tenant_id!},include:{global_competitors:true}})]);
 return {events,total,page,rules,competitors:competitors.map(c=>({id:c.global_competitor_id,name:c.global_competitors.competitor_name})),can_manage:permissions(req).all===true||permissions(req).manage_catalog===true};});res.json({data});
 }catch(e){next(e);}});
router.post('/rules',async(req:AppRequest,res,next)=>{try{
 if(permissions(req).all!==true&&permissions(req).manage_catalog!==true){res.sendStatus(403);return;}
 const q=rule.safeParse(req.body);if(!q.success){res.status(400).json({message:'Invalid price alert rule'});return;}
 const result=await scoped(req,async tx=>{if(!await tx.tenant_competitors.findFirst({where:{tenant_id:req.tenant_id!,global_competitor_id:q.data.global_competitor_id}}))return null;
 return tx.market_alert_rules.create({data:{...q.data,tenant_id:req.tenant_id!,metric:'PRICE_CHANGE_PERCENT'}});});
 if(!result){res.sendStatus(404);return;}res.status(201).json({data:result});
 }catch(e){next(e);}});
router.patch('/rules/:id',async(req:AppRequest,res,next)=>{try{
 if(permissions(req).all!==true&&permissions(req).manage_catalog!==true){res.sendStatus(403);return;}
 const q=rule.safeParse(req.body);if(!q.success||!z.uuid().safeParse(req.params.id).success){res.sendStatus(400);return;}
 const n=await scoped(req,async tx=>{if(!await tx.tenant_competitors.findFirst({where:{tenant_id:req.tenant_id!,global_competitor_id:q.data.global_competitor_id}}))return 0;
 return (await tx.market_alert_rules.updateMany({where:{tenant_id:req.tenant_id!,alert_rule_id:String(req.params.id),metric:'PRICE_CHANGE_PERCENT'},data:q.data})).count;});
 res.status(n?200:404).json({data:{updated:n===1}});
 }catch(e){next(e);}});
router.post('/events/:id/:action',async(req:AppRequest,res,next)=>{try{
 if(permissions(req).all!==true&&permissions(req).manage_catalog!==true){res.sendStatus(403);return;}
 if(!z.uuid().safeParse(req.params.id).success||!['acknowledge','resolve'].includes(String(req.params.action))){res.sendStatus(400);return;}
 const user=req.user!.user_id??req.user!.id,now=new Date();
 const n=await scoped(req,async tx=>(await tx.market_alert_events.updateMany({where:{tenant_id:req.tenant_id!,alert_event_id:String(req.params.id),...(req.params.action==='resolve'?{resolved_at:null}:{acknowledged_at:null,resolved_at:null})},data:req.params.action==='resolve'?{resolved_at:now,resolved_by:user}:{acknowledged_at:now,acknowledged_by:user}})).count);
 res.status(n?200:404).json({data:{updated:n===1}});
 }catch(e){next(e);}});
export default router;
