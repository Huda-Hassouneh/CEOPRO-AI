import type { Response as ExpressResponse } from "express";
import { RagDocumentProcessingError } from "../service/rag-search-text.js";
import { ERROR_CODES } from "../../../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "../../../errors/error-definitions.js";
import type { AppRequest } from "../../../types/request.js";
import { errorResponse, successResponse } from "../../../types/response.js";
import { isRagClientError } from "../client/rag.client.js";
import {getChatSession,listChatSessions,RagChatError} from "../repo/rag-chat.repo.js";
import {FeatureUsageCapacityError,FeatureUsageUnavailableError} from "../../features/repo/usage.repo.js";
import {z} from "zod";
import {
  deleteRagDocument,
  getRagChunkDetail,
  getRagDocuments,
  isRagServiceError,
  queryRag,
  reindexRagDocument,
  uploadRagDocument
} from "../service/rag.service.js";

type ErrorCode = (typeof ERROR_CODES)[keyof typeof ERROR_CODES];

function sendError(
  res: ExpressResponse,
  code: ErrorCode,
  detail?: unknown
): void {
  const definition = ERROR_DEFINITIONS[code];
  res
    .status(definition.statusCode)
    .json(
      errorResponse(
        definition.message,
        definition.statusCode,
        code,
        detail
      )
    );
}

function handleError(res: ExpressResponse, error: unknown): void {
  console.error("[RagController]", error);
  if (error instanceof RagDocumentProcessingError) {
    sendError(res, ERROR_CODES.SERVICE_UNAVAILABLE, {
      reason: "DOCUMENT_PROCESSING_UNAVAILABLE",
      message: "The server could not run its PDF text extractor. Check backend dependencies and the Node.js version."
    });
    return;
  }
  if(error instanceof FeatureUsageCapacityError || (error instanceof RagChatError && error.code==='USAGE_EXCEEDED')){
    sendError(res,ERROR_CODES.PAYMENT_REQUIRED,{reason:'USAGE_EXCEEDED',message:'RAG token allowance is insufficient.'});return;
  }
  if(error instanceof FeatureUsageUnavailableError){sendError(res,ERROR_CODES.FORBIDDEN,{reason:'FEATURE_NOT_INCLUDED'});return;}
  if(error instanceof RagChatError){
    const status=error.code==='SESSION_NOT_FOUND'?404:error.code==='INVALID_REQUEST'?400:
      ['CITATION_INVALID','USAGE_METADATA_INVALID','ANSWER_EMPTY'].includes(error.code)?502:409;
    res.status(status).json(errorResponse('RAG request could not be completed.',status,'RAG_'+error.code,{reason:error.code}));return;
  }

  if (isRagServiceError(error)) {
    switch (error.code) {
      case "INVALID_FILE_UPLOAD":
        sendError(
          res,
          ERROR_CODES.INVALID_FILE_UPLOAD,
          error.detail ?? error.message
        );
        return;
      case "FILE_SIZE_LIMIT_EXCEEDED":
        sendError(
          res,
          ERROR_CODES.FILE_SIZE_LIMIT_EXCEEDED,
          error.detail ?? error.message
        );
        return;
      case "FEATURE_NOT_INCLUDED":
        sendError(res, ERROR_CODES.FORBIDDEN, error.detail ?? error.message);
        return;
      case "USAGE_EXCEEDED":
      case "STORAGE_EXCEEDED":
        sendError(
          res,
          ERROR_CODES.PAYMENT_REQUIRED,
          error.detail ?? { message: error.message }
        );
        return;
      case "MALFORMED_HISTORY_JSON":
        sendError(
          res,
          ERROR_CODES.MALFORMED_HISTORY_JSON,
          error.detail ?? error.message
        );
        return;
      case "NO_DOCUMENTS":
        sendError(res, ERROR_CODES.INVALID_REQUEST, {
          reason: "NO_DOCUMENTS",
          message: error.message
        });
        return;
      case "DOCUMENT_DELETE_UNAVAILABLE":
      case "DOCUMENT_CONTENT_UNAVAILABLE":
        sendError(
          res,
          ERROR_CODES.INVALID_REQUEST,
          error.detail ?? error.message
        );
        return;
      case "NOT_FOUND":
        sendError(
          res,
          ERROR_CODES.RESOURCE_NOT_FOUND,
          error.detail ?? error.message
        );
        return;
    }
  }

  if (isRagClientError(error)) {
    if((error as {reason?:string}).reason==='ANSWER_EMPTY'){
      res.status(502).json(errorResponse('The AI returned an empty answer.',502,'RAG_ANSWER_EMPTY',{reason:'ANSWER_EMPTY'}));return;
    }
    const code =
      error.kind === "upstream_event" ||
      [500, 502, 503].includes(error.upstreamStatus ?? 0)
        ? ERROR_CODES.UPSTREAM_LLM_FAILURE
        : ERROR_CODES.EXTERNAL_SERVICE_ERROR;

    sendError(res, code, {
      message: error.message,
      upstream_status: error.upstreamStatus ?? null
    });
    return;
  }

  sendError(res, ERROR_CODES.INTERNAL_SERVER_ERROR);
}

function getTenantId(req: AppRequest, res: ExpressResponse): string | null {
  const tenantId = req.tenant_id;
  if (typeof tenantId !== "string" || !tenantId.trim()) {
    sendError(
      res,
      ERROR_CODES.FORBIDDEN,
      "Tenant context is required for this operation."
    );
    return null;
  }
  return tenantId;
}

function getUserId(req: AppRequest, res: ExpressResponse): string | null {
  const userId = req.user?.user_id;
  if (typeof userId !== "string" || !userId.trim()) {
    sendError(
      res,
      ERROR_CODES.FORBIDDEN,
      "Authenticated user context is required for this operation."
    );
    return null;
  }
  return userId;
}

export const ragController = {
  reindexDocument:async(req:AppRequest,res:ExpressResponse):Promise<void>=>{
    try{const tenantId=getTenantId(req,res),userId=getUserId(req,res);if(!tenantId||!userId)return;
      res.json(successResponse(await reindexRagDocument({tenantId,userId,documentId:String(req.params.document_id??'')}),'Search indexing finished'));
    }catch(error){handleError(res,error);}
  },
  listSessions:async(req:AppRequest,res:ExpressResponse):Promise<void>=>{
    try{const tenantId=getTenantId(req,res),userId=getUserId(req,res);if(!tenantId||!userId)return;
      res.json(successResponse({sessions:await listChatSessions({tenantId,userId})},'Conversations fetched'));
    }catch(error){handleError(res,error);}
  },
  getSession:async(req:AppRequest,res:ExpressResponse):Promise<void>=>{
    try{const tenantId=getTenantId(req,res),userId=getUserId(req,res);if(!tenantId||!userId)return;
      const sessionId=String(req.params.session_id??'');
      if(!z.string().uuid().safeParse(sessionId).success)throw new RagChatError('SESSION_NOT_FOUND');
      res.json(successResponse(await getChatSession({tenantId,userId},sessionId),'Conversation fetched'));
    }catch(error){handleError(res,error);}
  },
  deleteDocument: async (req:AppRequest,res:ExpressResponse):Promise<void> => {
    try {
      const tenantId=getTenantId(req,res);if(!tenantId)return;
      const userId=getUserId(req,res);if(!userId)return;
      const data=await deleteRagDocument({tenantId,userId,documentId:String(req.params.document_id??"")});
      res.status(200).json(successResponse(data,"Document deleted"));
    }catch(error){handleError(res,error);}
  },
  listDocuments: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    try {
      const tenantId = getTenantId(req, res);
      if (!tenantId) return;
      const userId = getUserId(req, res);
      if (!userId) return;

      const page = Number(req.query.page ?? 1);
      const data = await getRagDocuments({ tenantId, userId, page,
        search:typeof req.query.search==='string'?req.query.search:undefined,type:typeof req.query.type==='string'?req.query.type:undefined,
        sort:req.query.sort==='oldest'?'oldest':'newest' });

      res
        .status(200)
        .json(successResponse(data, "Documents fetched successfully"));
    } catch (error) {
      handleError(res, error);
    }
  },

  uploadDocument: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    try {
      const tenantId = getTenantId(req, res);
      if (!tenantId) return;

      const userId = getUserId(req, res);
      if (!userId) return;

      if (!req.file) {
        sendError(
          res,
          ERROR_CODES.INVALID_FILE_UPLOAD,
          "A multipart file upload is required in field 'file'."
        );
        return;
      }

      const data = await uploadRagDocument({
        tenantId,
        userId,
        file: {
          originalname: req.file.originalname,
          mimetype: req.file.mimetype,
          size: req.file.size,
          buffer: req.file.buffer
        }
      });

      res
        .status(201)
        .json(successResponse(data, "RAG document upload accepted"));
    } catch (error) {
      handleError(res, error);
    }
  },

  queryAssistant: async (
    req: AppRequest,
    res: ExpressResponse
  ): Promise<void> => {
    try {
      const tenantId = getTenantId(req, res);
      if (!tenantId) return;
      const userId = getUserId(req, res);
      if (!userId) return;

      const data = await queryRag({
        tenantId,
        userId,
        queryText: String(req.query.query_text),
        topK: Number(req.query.top_k ?? 5),
        sessionId:typeof req.query.session_id==='string'?req.query.session_id:undefined,
        requestId:typeof req.query.request_id==='string'?req.query.request_id:undefined,
        language:req.query.language==='ar'?'ar':'en',
        historyJson:
          typeof req.query.history_json === "string"
            ? req.query.history_json
            : undefined
      });

      res
        .status(200)
        .json(successResponse(data, "Assistant query successful"));
    } catch (error) {
      handleError(res, error);
    }
  },

  getChunk: async (req: AppRequest, res: ExpressResponse): Promise<void> => {
    try {
      const tenantId = getTenantId(req, res);
      if (!tenantId) return;
      const userId = getUserId(req, res);
      if (!userId) return;

      const chunkId = String(req.params.chunk_id || "").trim();
      if (!chunkId) {
        sendError(
          res,
          ERROR_CODES.INVALID_REQUEST,
          "chunk_id path parameter is required."
        );
        return;
      }

      const data = await getRagChunkDetail(tenantId, userId, chunkId);
      res
        .status(200)
        .json(successResponse(data, "Chunk fetched successfully"));
    } catch (error) {
      handleError(res, error);
    }
  }
};
