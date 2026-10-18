import { ragUploadProblem } from "./rag-upload.validation.js";
import { deleteStoredRagDocument, getRagDocumentPage } from "../repo/rag.repo.js";
import { createHash, randomUUID } from "node:crypto";
import { extname } from "node:path";
import { z } from "zod";
import { extractSearchContent,RAG_SEARCH_VERSION,searchRevision } from "./rag-search-text.js";
import {getRagDocumentForReindex,saveRagSearchContent} from '../repo/rag.repo.js';
import { ensureRagSearchIndex } from "./rag-search.service.js";
import { safeUploadName } from "../../dataconnection/types/dataconnection.validation.js";
import {
  FeatureUsageCapacityError,
  FeatureUsageUnavailableError,
  assertFeatureCapacity,
  getFeatureAccessInfo,
  getRemainingUsage
} from "../../features/repo/usage.repo.js";
import { beginChatRequest, failChatRequest, finishChatRequest, getChatSession, lookupChatRequest, RagChatError, recoverExpiredRagReservations } from "../repo/rag-chat.repo.js";
import { boundedHistory, evidenceIsInSource, ragHistorySchema, validTotalTokens } from "./rag-answer.validation.js";
import { queryRagAi, type RagAiDocument } from "../client/rag.client.js";
import {
  countRagDocuments,
  getRagChunk,
  getRagQueryDocuments,
  listRagDocuments,
  persistRagQuerySources,
  saveUploadedRagDocument
} from "../repo/rag.repo.js";
import {
  MAX_RAG_DOCUMENT_SIZE_BYTES,
  RAG_DOCUMENT_EXTENSIONS,
  type RagDocumentStatus,
  type RagQueryInput,
  type RagServiceError,
  type RagUploadInput
} from "../types/rag.types.js";

const ALLOWED_EXTENSIONS = new Set<string>(RAG_DOCUMENT_EXTENSIONS);
const MAX_QUERY_DOCUMENTS = 10;

function createRagServiceError(
  code: RagServiceError["code"],
  message: string,
  detail?: unknown
): RagServiceError {
  const error = new Error(message) as RagServiceError;
  error.name = "RagServiceError";
  error.code = code;
  error.detail = detail;
  return error;
}

export function isRagServiceError(error: unknown): error is RagServiceError {
  return error instanceof Error && error.name === "RagServiceError";
}

async function assertUploadEntitlements(input: {
  tenantId: string;
  fileSizeBytes: number;
}) {
  const kbUsed = Math.max(1, Math.ceil(input.fileSizeBytes / 1024));
  const extraction = await getRemainingUsage(
    input.tenantId,
    "document_extraction"
  );
  if (!extraction) {
    throw createRagServiceError(
      "FEATURE_NOT_INCLUDED",
      "Document extraction is not available for this subscription."
    );
  }
  if (
    extraction.isExceeded ||
    (extraction.remaining !== null && Number(extraction.remaining) <= 0)
  ) {
    throw createRagServiceError(
      "USAGE_EXCEEDED",
      "Document extraction quota has been reached.",
      {
        current_usage: extraction.currentUsage,
        limit: extraction.limit,
        remaining: 0,
        unit: "KB"
      }
    );
  }
  if (extraction.remaining !== null && kbUsed > Number(extraction.remaining)) {
    throw createRagServiceError(
      "USAGE_EXCEEDED",
      "This upload exceeds the remaining document extraction quota.",
      { requested: kbUsed, remaining: extraction.remaining, unit: "KB" }
    );
  }

  const storage = await assertFeatureCapacity({
    tenantId: input.tenantId,
    featureCode: "document_storage_mb",
    additionalAmount: input.fileSizeBytes / 1024 ** 2
  });
  if (!storage.allowed) {
    if (storage.reason === "FEATURE_NOT_INCLUDED") {
      throw createRagServiceError(
        "FEATURE_NOT_INCLUDED",
        "Document storage is not available for this subscription."
      );
    }
    throw createRagServiceError(
      "STORAGE_EXCEEDED",
      "This upload exceeds the available document storage capacity.",
      {
        feature_code: "document_storage_mb",
        reason: "CAPACITY_REACHED",
        current_usage: storage.entitlement.currentUsage,
        limit: storage.entitlement.limit,
        requested: input.fileSizeBytes / 1024 ** 2,
        remaining: storage.entitlement.remaining,
        unit: "MB"
      }
    );
  }
  return { kbUsed };
}

export async function uploadRagDocument(input: RagUploadInput) {
  const extension = extname(input.file.originalname).toLowerCase();
  if (!ALLOWED_EXTENSIONS.has(extension)) {
    throw createRagServiceError(
      "INVALID_FILE_UPLOAD",
      `Allowed RAG document extensions are ${RAG_DOCUMENT_EXTENSIONS.join(", ")}.`
    );
  }
  if (!Number.isFinite(input.file.size) || input.file.size <= 0) {
    throw createRagServiceError(
      "INVALID_FILE_UPLOAD",
      "The uploaded file is empty or has an invalid size."
    );
  }
  if (input.file.size > MAX_RAG_DOCUMENT_SIZE_BYTES) {
    throw createRagServiceError(
      "FILE_SIZE_LIMIT_EXCEEDED",
      "RAG documents must not exceed 2 MB."
    );
  }

  const problem=ragUploadProblem(input.file);
  if(problem)throw createRagServiceError("INVALID_FILE_UPLOAD",problem);

  const { kbUsed } = await assertUploadEntitlements({
    tenantId: input.tenantId,
    fileSizeBytes: input.file.size
  });
  const documentId = randomUUID();
  const fileName = safeUploadName(input.file.originalname);
  const searchContent = await extractSearchContent({file_name:fileName,source_file_content:input.file.buffer,rag_document_chunks:[]});
  if(searchContent.state==='unreadable')throw createRagServiceError('INVALID_FILE_UPLOAD','Document text could not be read. Check the format, encryption and extraction limits.');

  try {
    await saveUploadedRagDocument({
      tenantId: input.tenantId,
      userId: input.userId,
      documentId,
      fileName,
      fileSizeBytes: input.file.size,
      contentType: input.file.mimetype || "application/octet-stream",
      sourceFileContent: input.file.buffer,
      processedStatus: "Stored",
      extractionUsageKb: kbUsed,
      searchContent
    });
  } catch (error) {
    const message=error instanceof Error ? error.message : String(error);
    if (message.includes("DOCUMENT_STORAGE_CAPACITY_EXCEEDED"))
      throw createRagServiceError("STORAGE_EXCEEDED","Document storage capacity has been reached.",{feature_code:"document_storage_mb",reason:"CAPACITY_REACHED"});
    if (message.includes("DOCUMENT_STORAGE_NOT_INCLUDED"))
      throw createRagServiceError("FEATURE_NOT_INCLUDED","Document storage is not included.");
    if (error instanceof FeatureUsageCapacityError) {
      throw createRagServiceError(
        "USAGE_EXCEEDED",
        "Document extraction quota has been reached.",
        {
          feature_code: error.capacity.featureCode,
          current_usage: error.capacity.currentUsage,
          limit: error.capacity.limit,
          remaining: error.capacity.remaining,
          requested: error.capacity.requested,
          unit: "KB"
        }
      );
    }
    if (error instanceof FeatureUsageUnavailableError) {
      throw createRagServiceError(
        "FEATURE_NOT_INCLUDED",
        "Document extraction is not available for this subscription."
      );
    }
    throw error;
  }

  return {
    document_id: documentId,
    file_name: fileName,
    processed_status: "Stored" as RagDocumentStatus
  };
}

export async function getRagDocuments(input: {
  tenantId: string;
  userId: string;
  page: number;
  pageSize?: number;
  search?:string;type?:string;sort?:'newest'|'oldest';
}) {
  const pageSize = input.pageSize ?? 3;
  const {documents,total,storage}=await getRagDocumentPage({...input,pageSize});

  return {
    storage,
    documents: documents.map(({storage_bucket_path,search_index,...document}) => ({
      ...document,
      storage_owned_by_node: storage_bucket_path.startsWith("ceopro-db://"),
      search_state:search_index?.index_version===RAG_SEARCH_VERSION?search_index.content_state:'pending',
      file_size_bytes: document.file_size_bytes.toString()
    })),
    pagination: {
      page: input.page,
      pageSize,
      total,
      totalPages: Math.ceil(total / pageSize)
    }
  };
}

export async function queryRag(input: RagQueryInput) {
  const access=await getFeatureAccessInfo(input.tenantId,"rag_assistant");
  if(!access.subscription || !access.planFeature)throw createRagServiceError("FEATURE_NOT_INCLUDED","RAG assistant is not included.");
  if(!input.queryText.trim() || input.queryText.length>2000)throw new RagChatError('INVALID_REQUEST');
  let legacyHistory:Array<{role:'user'|'assistant';content:string}>=[];
  if(input.historyJson!==undefined){
    try {legacyHistory=ragHistorySchema.parse(JSON.parse(input.historyJson));}
    catch{throw createRagServiceError('MALFORMED_HISTORY_JSON','History must contain at most 20 user/assistant messages.');}
  }
  const requestId=input.requestId??randomUUID();
  if(!z.string().uuid().safeParse(requestId).success || (input.sessionId && !z.string().uuid().safeParse(input.sessionId).success))throw new RagChatError('INVALID_REQUEST');
  const hash=createHash('sha256').update(JSON.stringify([input.queryText.trim(),input.topK,input.sessionId??null,legacyHistory,input.language??'en'])).digest('hex');
  await recoverExpiredRagReservations(input);
  const cached=await lookupChatRequest(input,requestId,hash);
  if(cached)return cached;
  const allowance=await getRemainingUsage(input.tenantId,'rag_assistant');
  if(!allowance || allowance.isExceeded || allowance.remaining===0)throw createRagServiceError('USAGE_EXCEEDED','RAG token allowance is insufficient.');
  const preceding=input.sessionId?(await getChatSession(input,input.sessionId)).turns
    .filter(turn=>turn.status==='completed').slice(-2).map(turn=>turn.question):
    legacyHistory.filter(turn=>turn.role==='user').slice(-2).map(turn=>turn.content);
  await ensureRagSearchIndex(input);
  const storedDocuments = await getRagQueryDocuments({
    tenantId: input.tenantId,
    userId: input.userId,
    limit: MAX_QUERY_DOCUMENTS,
    queryText: [input.queryText,...preceding].join('\n')
  });
  const aiDocuments: RagAiDocument[] = [];
  const documentByAiName = new Map<
    string,
    { documentId: string; fileName: string; text:string; revision:string }
  >();

  for (const document of storedDocuments) {
    const index=document.search_index;
    if(!index || index.content_state!=='ready' || !index.source_text.trim())continue;
    const aiFileName=`${document.document_id}_${document.file_name}.md`;
    aiDocuments.push({file_name:aiFileName,text:index.source_text});
    documentByAiName.set(aiFileName,{documentId:document.document_id,fileName:document.file_name,text:index.source_text,revision:index.source_revision});
  }

  if (aiDocuments.length === 0) {
    throw createRagServiceError(
      "NO_DOCUMENTS",
      "Upload at least one processed RAG document before asking a question."
    );
  }

  let begun=false;
  try {
    const {sessionId,history}=await beginChatRequest(input,{requestId,hash,sessionId:input.sessionId,question:input.queryText.trim()});
    begun=true;
    const data=await queryRagAi({documents:aiDocuments,queryText:input.queryText,topK:input.topK,
      history:boundedHistory(input.sessionId?history:legacyHistory)});
    if(!data.answer.trim())throw new RagChatError('ANSWER_EMPTY');
    const totalTokens=validTotalTokens(data.token_usage);
    if(totalTokens===null)throw new RagChatError('USAGE_METADATA_INVALID');
    const indices=new Set<number>();
    const sources=data.sources.map(source=>{
      const document=documentByAiName.get(source.document);
      if(!document || indices.has(source.source_index) || !evidenceIsInSource(source.text,document.text))throw new RagChatError('CITATION_INVALID');
      indices.add(source.source_index);
      return {documentId:document.documentId,fileName:document.fileName,revision:document.revision,text:source.text,
        source_index:source.source_index,chunk_index:source.chunk_index,score:source.score};
    });
    const unavailable=input.language==='ar'?'لم أجد أدلة تدعم الإجابة عن هذا السؤال في مستنداتك.':'I could not find supporting evidence in your documents for this question.';
    return await finishChatRequest(input,{requestId,sessionId,tokens:totalTokens,
      answer:sources.length?data.answer:unavailable,evidenceStatus:sources.length?'supported':'insufficient',sources});
  }catch(error){
    if(begun)await failChatRequest(input,requestId,error instanceof RagChatError?error.code:'AI_REQUEST_FAILED');
    throw error;
  }

}

export async function getRagChunkDetail(
  tenantId: string,
  userId: string,
  chunkId: string
) {
  if(!z.string().uuid().safeParse(chunkId).success)throw createRagServiceError('NOT_FOUND','Citation not found.');
  const chunk = await getRagChunk({ tenantId, userId, chunkId });
  if (!chunk) {
    throw createRagServiceError(
      "NOT_FOUND",
      "Citation chunk not found or access denied."
    );
  }
  return {
    chunk_id: chunk.chunk_id,
    document_id:chunk.document_id,
    text_content: chunk.chunk_text_content,
    file_name: chunk.rag_documents_metadata?.file_name || "Unknown File"
  };
}
export async function reindexRagDocument(input:{tenantId:string;userId:string;documentId:string}){
 if(!z.string().uuid().safeParse(input.documentId).success)throw createRagServiceError('NOT_FOUND','Document not found.');
 const document=await getRagDocumentForReindex(input);
 if(!document)throw createRagServiceError('NOT_FOUND','Document not found or externally managed.');
 const revision=searchRevision(document),content=await extractSearchContent(document);
 if(!await saveRagSearchContent({...input,document,revision,content,reprocess:true}))throw new RagChatError('SOURCE_CHANGED');
 return {document_id:input.documentId,search_state:content.state};
}

export async function deleteRagDocument(input: {tenantId:string;userId:string;documentId:string}) {
  if(!z.string().uuid().safeParse(input.documentId).success)throw createRagServiceError("NOT_FOUND","Document not found.");
  const result=await deleteStoredRagDocument(input);
  if(result.status==="external")throw createRagServiceError("DOCUMENT_DELETE_UNAVAILABLE","This document is managed by external storage and requires its storage owner's deletion flow.");
  if(result.status==="not_found")throw createRagServiceError("NOT_FOUND","Document not found.");
  return {document_id:input.documentId,deleted:true};
}
