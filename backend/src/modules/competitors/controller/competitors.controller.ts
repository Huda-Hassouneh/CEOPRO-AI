import {requireCompetitorAiActions} from '../service/competitor-capabilities.js';
import type { Response,NextFunction } from 'express';
import type { AppRequest } from '../../../types/request.js';
import { sendApiError } from '../../../utils/http.js';
import { CompetitorError } from '../types/competitors.types.js';
import { competitorCreateSchema,competitorListSchema,competitorUpdateSchema,competitorTrackingSchema,mappingConfirmationSchema,sourceReviewSchema,collectionRetrySchema } from '../types/competitors.validation.js';
import { competitorsService as service } from '../service/competitors.service.js';
import {productLinkSchema,candidateDecisionSchema,catalogSearchSchema} from '../types/competitors.validation.js';
const uuid=(value:unknown):value is string=>typeof value==='string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
type Operation='list'|'profile'|'create'|'update'|'track'|'schedule'|'confirm'|'discover'|'cancelDiscovery'|'reviewSource'|'retryCollection'|'linkProduct'|'rejectCandidate'|'previewProduct'|'catalogProducts'|'productCandidates';
export const handleCompetitor=(operation:Operation)=>async(req:AppRequest,res:Response,next:NextFunction)=>{
  try {
    if(!req.tenant_id || !req.user?.id) return sendApiError(res,'TENANT_ACCESS_DENIED');
    if(!['list','profile','update'].includes(operation)) requireCompetitorAiActions();
    const scope={tenantId:req.tenant_id,userId:req.user.id}; const id=req.params.competitorId;
    if(!['list','create','discover'].includes(operation) && !uuid(id)) return sendApiError(res,'INVALID_PARAMETER');
    if(operation==='cancelDiscovery' && !uuid(req.params.eventId)) return sendApiError(res,'INVALID_PARAMETER');
    if(['reviewSource','retryCollection'].includes(operation) && !uuid(req.params.sourceId)) return sendApiError(res,'INVALID_PARAMETER');
    if(['confirm','previewProduct'].includes(operation) && !uuid(req.params.mappingId)) return sendApiError(res,'INVALID_PARAMETER');
    if(operation==='productCandidates') {
      if(!uuid(req.params.productId))return sendApiError(res,'INVALID_PARAMETER');
      return res.status(200).json({status:'success',data:await service.productCandidates(scope,id as string,req.params.productId as string)});
    }
    if(operation==='rejectCandidate' && !uuid(req.params.candidateId)) return sendApiError(res,'INVALID_PARAMETER');
    if(['linkProduct','rejectCandidate','catalogProducts','previewProduct'].includes(operation)) {
      const payload=operation==='catalogProducts'?catalogSearchSchema.safeParse(req.query):operation==='linkProduct'?productLinkSchema.safeParse(req.body):operation==='rejectCandidate'?candidateDecisionSchema.safeParse(req.body):{success:true as const,data:{}};
      if(!payload.success) return sendApiError(res,'INVALID_PARAMETER');
      const result=operation==='linkProduct'?await service.linkProduct(scope,id as string,payload.data as Parameters<typeof service.linkProduct>[2])
        :operation==='previewProduct'?await service.previewProduct(scope,id as string,req.params.mappingId as string)
        :operation==='rejectCandidate'?await service.rejectCandidate(scope,id as string,req.params.candidateId as string)
        :await service.catalogProducts(scope,id as string,payload.data as {search:string;page:number});
      return res.status(200).json({status:'success',data:result});
    }
    const schema=operation==='retryCollection'?collectionRetrySchema:operation==='reviewSource'?sourceReviewSchema:operation==='list'?competitorListSchema:operation==='create'?competitorCreateSchema:operation==='update'?competitorUpdateSchema:operation==='track'?competitorTrackingSchema:mappingConfirmationSchema;
    const parsed=['profile','schedule','discover','cancelDiscovery'].includes(operation)?null:schema.safeParse(operation==='list'?req.query:req.body);
    if(parsed && !parsed.success) return sendApiError(res,'INVALID_PARAMETER',{details:{issues:parsed.error.issues.map(issue=>({field:issue.path.join('.'),message:issue.message}))}});
    const data=parsed?.success?parsed.data:undefined;
    const result=operation==='retryCollection'?await service.retryCollection(scope,id as string,req.params.sourceId as string,(data as {failedEventId:string}).failedEventId)
      :operation==='reviewSource'?await service.reviewSource(scope,id as string,req.params.sourceId as string,data as Parameters<typeof service.reviewSource>[3])
      :operation==='cancelDiscovery'?await service.cancelDiscovery(scope,id as string,req.params.eventId as string)
      :operation==='discover'?await service.discover(scope)
      :operation==='list'?await service.list(scope,(data as {status:'active'|'inactive'|'all'}).status)
      :operation==='create'?await service.create(scope,data as Parameters<typeof service.create>[1])
      :operation==='profile'?await service.profile(scope,id as string)
      :operation==='update'?await service.update(scope,id as string,(data as {alias:string|null}).alias)
      :operation==='track'?await service.track(scope,id as string,(data as {isTracked:boolean}).isTracked)
      :operation==='confirm'?await service.confirm(scope,id as string,req.params.mappingId as string,(data as {comparisonConfirmed:boolean}).comparisonConfirmed)
      :await service.schedule(scope,id as string);
    if(operation==='list') { const list=result as Awaited<ReturnType<typeof service.list>>; return res.status(200).json({status:'success',data:list.competitors,meta:{capacity:list.capacity,canEdit:list.canEdit,monitoringFrequencyMinutes:list.monitoringFrequencyMinutes}}); }
    return res.status(operation==='create'?201:200).json({status:'success',data:result});
  } catch(error) {
    if(error instanceof CompetitorError) return sendApiError(res,error.code,{details:error.details});
    const message=String((error as {message?:unknown})?.message ?? '');
    if(/COMPETITOR_CAPACITY_(EXCEEDED|NOT_CONFIGURED)/.test(message)) return sendApiError(res,'COMPETITOR_CAPACITY_EXCEEDED');
    if((error as {code?:string})?.code==='P2002') return sendApiError(res,'COMPETITOR_IDENTITY_AMBIGUOUS');
    next(error);
  }
};
