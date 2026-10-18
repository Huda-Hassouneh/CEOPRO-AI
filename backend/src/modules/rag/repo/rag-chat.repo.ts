import {randomUUID} from "node:crypto";
import {prisma} from "../../../config/database.js";
import type {Prisma} from "../../../generated/prisma/client.js";
import {getFeatureAccessInfo,reserveFeatureUsageInTransaction,releaseFeatureUsageInTransaction} from "../../features/repo/usage.repo.js";
import {persistRagQuerySources} from "./rag.repo.js";
import {RAG_SEARCH_VERSION} from "../service/rag-search-text.js";

type Context={tenantId:string;userId:string};
export type ChatResult={answer:string;sources:Array<Record<string,unknown>>;evidence_status:"supported"|"insufficient";session_id:string;request_id:string};
type RequestRow={request_id:string;session_id:string;request_hash:string;question:string;status:string;response:ChatResult|null;created_at:Date;lease_status:string;expires_at:Date};
type Hold={request_id:string;user_id:string;usage_record_id:string;reserved_tokens:number;allocation_limit:number|null;status:string};
export class RagChatError extends Error {constructor(public code:string){super(code);this.name="RagChatError";}}
async function context(tx:Prisma.TransactionClient,c:Context){
 await tx.$executeRaw`SELECT set_config('app.current_tenant_id',${c.tenantId},true),set_config('app.current_user_id',${c.userId},true)`;
}
async function quotaLock(tx:Prisma.TransactionClient,c:Context){
 await tx.$executeRaw`SELECT pg_advisory_xact_lock(hashtextextended(${'metered-usage:'+c.tenantId+':rag_assistant'},0))`;
}
async function expireHolds(tx:Prisma.TransactionClient,c:Context){
 const rows=await tx.$queryRaw<Hold[]>`SELECT * FROM public.rag_token_reservations
   WHERE tenant_id=${c.tenantId}::uuid AND status='pending' AND expires_at<=now() FOR UPDATE`;
 for(const row of rows){
  await releaseFeatureUsageInTransaction(tx,c.tenantId,'rag_assistant',row.reserved_tokens,row.usage_record_id);
  await tx.$executeRaw`UPDATE public.rag_token_reservations SET status='released' WHERE tenant_id=${c.tenantId}::uuid AND user_id=${row.user_id}::uuid AND request_id=${row.request_id}::uuid`;
 }
}
export async function recoverExpiredRagReservations(c:Context){
 await prisma.$transaction(async tx=>{await context(tx,c);await quotaLock(tx,c);await expireHolds(tx,c);});
}
async function sourceRevisions(tx:Prisma.TransactionClient,c:Context,sources:Array<Record<string,unknown>>){
 const ids=[...new Set(sources.map(s=>String(s.document_id)))];
 if(!ids.length)return new Map<string,string>();
 const rows=await tx.rag_document_search.findMany({where:{tenant_id:c.tenantId,document_id:{in:ids},index_version:RAG_SEARCH_VERSION,
   document:{processed_status:{in:['Stored','Processed']}}},select:{document_id:true,source_revision:true}});
 return new Map(rows.map(row=>[row.document_id,row.source_revision]));
}
function sourcesMatch(response:ChatResult,revisions:Map<string,string>){
 return response.sources.every(s=>revisions.get(String(s.document_id))===s.source_revision);
}
async function sourcesCurrent(tx:Prisma.TransactionClient,c:Context,response:ChatResult):Promise<boolean>{
 return sourcesMatch(response,await sourceRevisions(tx,c,response.sources));
}
async function requests(tx:Prisma.TransactionClient,c:Context,sessionId:string,limit=100){
 const rows=await tx.$queryRaw<RequestRow[]>`SELECT r.*,h.status AS lease_status,h.expires_at
   FROM public.rag_chat_requests r JOIN public.rag_token_reservations h USING(tenant_id,user_id,request_id)
   WHERE r.tenant_id=${c.tenantId}::uuid AND r.user_id=${c.userId}::uuid AND r.session_id=${sessionId}::uuid
   ORDER BY r.created_at DESC,r.request_id DESC LIMIT ${limit}`;
 const result=[];
 const revisions=await sourceRevisions(tx,c,rows.flatMap(row=>row.response?.sources??[]));
 for(const row of rows.reverse()){
  const valid=row.status==='completed' && row.response && sourcesMatch(row.response,revisions);
  result.push({...row,response:valid?row.response:null,status:valid?'completed':row.status==='pending'&&row.lease_status==='pending'?'pending':'unavailable'});
 }
 return result;
}
export async function listChatSessions(c:Context){
 return prisma.$transaction(async tx=>{await context(tx,c);await quotaLock(tx,c);await expireHolds(tx,c);
  return tx.$queryRaw<Array<{session_id:string;title:string;updated_at:Date}>>`SELECT session_id,title,updated_at FROM public.rag_chat_sessions
   WHERE tenant_id=${c.tenantId}::uuid AND user_id=${c.userId}::uuid ORDER BY updated_at DESC,session_id DESC LIMIT 50`;
 });
}
export async function getChatSession(c:Context,sessionId:string){
 return prisma.$transaction(async tx=>{await context(tx,c);await quotaLock(tx,c);await expireHolds(tx,c);
  const rows=await tx.$queryRaw<Array<{session_id:string;title:string}>>`SELECT session_id,title FROM public.rag_chat_sessions WHERE tenant_id=${c.tenantId}::uuid AND user_id=${c.userId}::uuid AND session_id=${sessionId}::uuid`;
  if(!rows.length)throw new RagChatError('SESSION_NOT_FOUND');
  return {...rows[0],turns:await requests(tx,c,sessionId)};
 });
}
export async function lookupChatRequest(c:Context,requestId:string,hash:string){
 return prisma.$transaction(async tx=>{await context(tx,c);await quotaLock(tx,c);await expireHolds(tx,c);
  const rows=await tx.$queryRaw<RequestRow[]>`SELECT r.*,h.status AS lease_status,h.expires_at FROM public.rag_chat_requests r
   JOIN public.rag_token_reservations h USING(tenant_id,user_id,request_id)
   WHERE r.tenant_id=${c.tenantId}::uuid AND r.user_id=${c.userId}::uuid AND r.request_id=${requestId}::uuid`;
  const row=rows[0];if(!row)return null;
  if(row.request_hash!==hash)throw new RagChatError('REQUEST_CONFLICT');
  if(row.status==='completed' && row.response){
   if(!await sourcesCurrent(tx,c,row.response))throw new RagChatError('SOURCE_CHANGED');
   return row.response;
  }
  throw new RagChatError(row.lease_status==='pending'?'REQUEST_PENDING':'REQUEST_FAILED');
 });
}
export async function beginChatRequest(c:Context,input:{requestId:string;hash:string;sessionId?:string;question:string}){
 return prisma.$transaction(async tx=>{await context(tx,c);await quotaLock(tx,c);await expireHolds(tx,c);
  const existing=await tx.$queryRaw<Array<{request_id:string}>>`SELECT request_id FROM public.rag_chat_requests WHERE tenant_id=${c.tenantId}::uuid AND user_id=${c.userId}::uuid AND request_id=${input.requestId}::uuid`;
  if(existing.length)throw new RagChatError('REQUEST_PENDING');
  const sessionId=input.sessionId??randomUUID();
  if(input.sessionId){
   const session=await tx.$queryRaw<Array<{session_id:string}>>`SELECT session_id FROM public.rag_chat_sessions WHERE tenant_id=${c.tenantId}::uuid AND user_id=${c.userId}::uuid AND session_id=${sessionId}::uuid FOR UPDATE`;
   if(!session.length)throw new RagChatError('SESSION_NOT_FOUND');
  }else await tx.$executeRaw`INSERT INTO public.rag_chat_sessions(tenant_id,user_id,session_id,title) VALUES(${c.tenantId}::uuid,${c.userId}::uuid,${sessionId}::uuid,${input.question.slice(0,100)})`;
  const pending=await tx.$queryRaw<Array<{request_id:string}>>`SELECT r.request_id FROM public.rag_chat_requests r
   JOIN public.rag_token_reservations h USING(tenant_id,user_id,request_id) WHERE r.tenant_id=${c.tenantId}::uuid AND r.user_id=${c.userId}::uuid AND r.session_id=${sessionId}::uuid AND h.status='pending'`;
  if(pending.length)throw new RagChatError('REQUEST_PENDING');
  const history=(await requests(tx,c,sessionId,10)).flatMap(row=>row.status==='completed'&&row.response?[
   {role:'user' as const,content:row.question},{role:'assistant' as const,content:row.response.answer}
  ]:[]);
  const reservation=await reserveFeatureUsageInTransaction(tx,c.tenantId,'rag_assistant',1,true);
  const budget=Math.min(8192,(reservation.remaining??8191)+1);
  if(budget>1)await tx.subscriptionUsage.update({where:{id:reservation.usageRecordId},data:{current_usage:{increment:budget-1}}});
  await tx.$executeRaw`INSERT INTO public.rag_token_reservations(tenant_id,user_id,request_id,usage_record_id,reserved_tokens,allocation_limit,status,expires_at)
   VALUES(${c.tenantId}::uuid,${c.userId}::uuid,${input.requestId}::uuid,${reservation.usageRecordId}::uuid,${budget},${reservation.limit},'pending',now()+interval '10 minutes')`;
  await tx.$executeRaw`INSERT INTO public.rag_chat_requests(tenant_id,user_id,request_id,session_id,request_hash,question,status)
   VALUES(${c.tenantId}::uuid,${c.userId}::uuid,${input.requestId}::uuid,${sessionId}::uuid,${input.hash},${input.question},'pending')`;
  return {sessionId,history};
 });
}
export async function failChatRequest(c:Context,requestId:string,code:string){
 return prisma.$transaction(async tx=>{await context(tx,c);await quotaLock(tx,c);
  const rows=await tx.$queryRaw<Hold[]>`SELECT * FROM public.rag_token_reservations WHERE tenant_id=${c.tenantId}::uuid AND user_id=${c.userId}::uuid AND request_id=${requestId}::uuid FOR UPDATE`;
  const row=rows[0];if(!row || row.status!=='pending')return;
  await releaseFeatureUsageInTransaction(tx,c.tenantId,'rag_assistant',row.reserved_tokens,row.usage_record_id);
  await tx.$executeRaw`UPDATE public.rag_token_reservations SET status='released' WHERE tenant_id=${c.tenantId}::uuid AND user_id=${c.userId}::uuid AND request_id=${requestId}::uuid`;
  await tx.$executeRaw`UPDATE public.rag_chat_requests SET status='failed',failure_code=${code} WHERE tenant_id=${c.tenantId}::uuid AND user_id=${c.userId}::uuid AND request_id=${requestId}::uuid`;
 });
}
export async function finishChatRequest(c:Context,input:{requestId:string;sessionId:string;tokens:number;answer:string;evidenceStatus:'supported'|'insufficient';sources:Array<{documentId:string;fileName:string;revision:string;text:string;source_index:number;chunk_index:number;score:number}>}):Promise<ChatResult>{
 return prisma.$transaction(async tx=>{await context(tx,c);await quotaLock(tx,c);
  const rows=await tx.$queryRaw<Hold[]>`SELECT * FROM public.rag_token_reservations WHERE tenant_id=${c.tenantId}::uuid AND user_id=${c.userId}::uuid AND request_id=${input.requestId}::uuid AND expires_at>now() FOR UPDATE`;
  const hold=rows[0];if(!hold || hold.status!=='pending')throw new RagChatError('REQUEST_EXPIRED');
  for(const source of [...input.sources].sort((a,b)=>a.documentId.localeCompare(b.documentId))){
   const current=await tx.$queryRaw<Array<{source_revision:string}>>`SELECT s.source_revision FROM public.rag_document_search s JOIN public.rag_documents_metadata d USING(tenant_id,document_id)
    WHERE s.tenant_id=${c.tenantId}::uuid AND s.document_id=${source.documentId}::uuid AND d.processed_status IN ('Stored','Processed') FOR SHARE OF s,d`;
   if(current[0]?.source_revision!==source.revision)throw new RagChatError('SOURCE_CHANGED');
  }
  const delta=input.tokens-hold.reserved_tokens;
  if(delta>0){
   const allocation=await tx.subscriptionUsage.findUnique({where:{id:hold.usage_record_id}});
   const access=await getFeatureAccessInfo(c.tenantId,'rag_assistant',tx);
   if(!allocation || !access.subscription || !access.planFeature || access.subscription.id!==allocation.subscription_id ||
     (access.planFeature.feature.resetCycle!=='lifetime' && access.subscription.currentPeriodStart.getTime()!==allocation.period_start.getTime()))throw new RagChatError('USAGE_EXCEEDED');
   const limit=access.planFeature.limit_value;
   const adjusted=await tx.subscriptionUsage.updateMany({where:{id:hold.usage_record_id,...(limit===null?{}:{current_usage:{lte:limit-delta}})},data:{current_usage:{increment:delta}}});
   if(!adjusted.count)throw new RagChatError('USAGE_EXCEEDED');
  }else if(delta<0)await releaseFeatureUsageInTransaction(tx,c.tenantId,'rag_assistant',-delta,hold.usage_record_id);
  const saved=await persistRagQuerySources({...c,sources:input.sources.map(s=>({documentId:s.documentId,text:s.text}))},tx);
  const response:ChatResult={answer:input.answer,evidence_status:input.evidenceStatus,session_id:input.sessionId,request_id:input.requestId,
   sources:input.sources.map((s,i)=>({source_index:s.source_index,document:s.fileName,document_id:s.documentId,chunk_id:saved[i]!.chunkId,text:s.text,score:s.score,chunk_index:s.chunk_index,source_revision:s.revision}))};
  await tx.$executeRaw`UPDATE public.rag_token_reservations SET status='settled',billed_tokens=${input.tokens} WHERE tenant_id=${c.tenantId}::uuid AND user_id=${c.userId}::uuid AND request_id=${input.requestId}::uuid`;
  await tx.$executeRaw`UPDATE public.rag_chat_requests SET status='completed',response=${JSON.stringify(response)}::jsonb WHERE tenant_id=${c.tenantId}::uuid AND user_id=${c.userId}::uuid AND request_id=${input.requestId}::uuid`;
  await tx.$executeRaw`UPDATE public.rag_chat_sessions SET updated_at=now() WHERE tenant_id=${c.tenantId}::uuid AND user_id=${c.userId}::uuid AND session_id=${input.sessionId}::uuid`;
  return response;
 });
}
