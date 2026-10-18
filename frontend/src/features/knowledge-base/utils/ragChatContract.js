export function mapRagSources(sources=[]) {
 return sources.map(source=>({
  citationId:`${source.chunk_id}-${source.source_index}`,documentId:source.document_id,chunkId:source.chunk_id,
  documentName:source.document,name:source.document,excerpt:source.text,score:source.score,
  sourceIndex:source.source_index,sourceType:'knowledge-base'
 }));
}
export function mapRagReply(payload){
 return {messageId:`${payload.request_id}-assistant`,role:'assistant',content:payload.answer,
  sources:mapRagSources(payload.sources),evidenceStatus:payload.evidence_status,createdAt:new Date().toISOString()};
}
export function mapRagTurns(turns,t){
 return turns.flatMap(turn=>[
  {messageId:`${turn.request_id}-user`,role:'user',content:turn.question,createdAt:turn.created_at},
  turn.response?{...mapRagReply(turn.response),createdAt:turn.created_at}:
   {messageId:`${turn.request_id}-assistant`,role:'assistant',status:'error',content:t(turn.status==='pending'?'ragAssistant.history.pending':'ragAssistant.history.unavailable'),createdAt:turn.created_at}
 ]);
}
export function reuseRagRequest(error){
 const code=error?.response?.data?.error?.code;
 return !error?.response || code==='RAG_REQUEST_PENDING' ||
  (error.response.status>=500 && !['RAG_CITATION_INVALID','RAG_USAGE_METADATA_INVALID','RAG_ANSWER_EMPTY'].includes(code));
}
