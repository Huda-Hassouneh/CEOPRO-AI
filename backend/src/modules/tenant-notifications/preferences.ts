import {Router} from 'express';import {z} from 'zod';import {prisma} from '../../config/database.js';import type {AppRequest} from '../../types/request.js';
const router=Router();
const category=z.enum(['business','market','imports']);
router.get('/',async(req:AppRequest,res,next)=>{try{
 const result=await prisma.$transaction(async tx=>{await tx.$queryRaw`SELECT set_config('app.current_tenant_id',${req.tenant_id!},true),set_config('app.current_user_id',${req.user!.user_id??req.user!.id},true)`;
 return tx.$queryRaw<{category:string,enabled:boolean}[]>`SELECT category,enabled FROM tenant_notification_preferences WHERE tenant_id=${req.tenant_id!}::uuid AND user_id=${req.user!.user_id??req.user!.id}::uuid`;});
 res.json({data:['business','market','imports'].map(category=>({category,enabled:result.find(r=>r.category===category)?.enabled??true}))});
 }catch(e){next(e);}});
router.put('/:category',async(req:AppRequest,res,next)=>{try{
 const c=category.safeParse(req.params.category),b=z.object({enabled:z.boolean()}).strict().safeParse(req.body);if(!c.success||!b.success){res.sendStatus(400);return;}
 await prisma.$transaction(async tx=>{await tx.$queryRaw`SELECT set_config('app.current_tenant_id',${req.tenant_id!},true),set_config('app.current_user_id',${req.user!.user_id??req.user!.id},true)`;
 await tx.$executeRaw`INSERT INTO tenant_notification_preferences(tenant_id,user_id,category,enabled) VALUES(${req.tenant_id!}::uuid,${req.user!.user_id??req.user!.id}::uuid,${c.data},${b.data.enabled}) ON CONFLICT(tenant_id,user_id,category) DO UPDATE SET enabled=EXCLUDED.enabled`;});res.json({data:{category:c.data,enabled:b.data.enabled}});
 }catch(e){next(e);}});
export default router;
