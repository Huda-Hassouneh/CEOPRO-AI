import { translateCurrent } from '../../../shared/lib/i18n.js';
import { getInvalidRagUploadFile, documentStorageStatus } from "../utils/ragUploadContract.js";
import httpClient from "../../../shared/lib/httpClient.js";
import { UI_TESTING_MODE } from "../../../shared/config/uiTestingMode.js";
import {mapRagReply} from '../utils/ragChatContract.js';

const capabilities = Object.freeze({
  chat: true,
  streaming: false,
  conversationHistory: true,
  documentUpload: true, // Updated to enable upload functionality
  documentPreview: false,
  documentActions: true,
  messageAttachments: false,
  imageInput: false
});

const createMessageId = () =>
  globalThis.crypto?.randomUUID?.() || `assistant-${Date.now()}`;

export const knowledgeBaseApi = {
  getCapabilities: async () => capabilities,
  listSessions:async(signal)=>{
    const response=await httpClient.get('/features/rag/sessions',{signal});return response.data?.data??response.data;
  },
  getSession:async(sessionId,signal)=>{
    const response=await httpClient.get(`/features/rag/sessions/${encodeURIComponent(sessionId)}`,{signal});return response.data?.data??response.data;
  },

  chat: async ({ question, attachments = [], signal,requestId,sessionId,language='en' } = {}) => {
    if (!question?.trim()) throw new Error(translateCurrent("interfaceCopy.noQuestion"));
    if (attachments.length) {
      const error = new Error(
        translateCurrent("interfaceCopy.attachmentsUnsupported")
      );
      error.code = "BACKEND_CAPABILITY_UNAVAILABLE";
      throw error;
    }
    if (UI_TESTING_MODE) {
      return {
        available: true,
        preview: true,
        message: {
          messageId: createMessageId(), role: "assistant",
          content: translateCurrent("ragAssistant.chat.demoResponse"),
          sources: [{ documentId: "preview-document-1", name: "Demo_Flower_Shop_Sales_2026.xlsx", score: 0.93 }],
          createdAt: new Date().toISOString(),
        },
      };
    }

    const response = await httpClient.post(
      "/features/rag/query",
      {},
      {
        params: { query_text: question.trim(), top_k: 5,request_id:requestId,session_id:sessionId??undefined,language },
        signal
      }
    );
    const payload = response.data?.data ?? response.data;
    return {available:true,sessionId:payload.session_id,requestId:payload.request_id,message:mapRagReply(payload)};
  },

  // frontend/src/features/knowledge-base/api/knowledgeBaseApi.js

  listDocuments: async ({ page = 1,search='',type='all',sort='newest' } = {}) => {
    try {
      const response = await httpClient.get("/features/rag/documents", {
        params: { page,search:search||undefined,type,sort }
      });

      const payload = response.data?.data ?? response.data;
      const mappedDocuments = (payload.documents || []).map((doc) => ({
        id: doc.document_id,
        name: doc.file_name,
        type: doc.content_type,
        uploadedAt: doc.uploaded_at,
        size: Number(doc.file_size_bytes), // Convert string back to number for formatSize
        status: documentStorageStatus(doc.processed_status, payload.storage?.retrievalMode),
        searchState:doc.search_state??'pending',
        canDelete: Boolean(doc.storage_owned_by_node)
      }));

      return {
        storage: payload.storage,
        documents: mappedDocuments,
        pagination: payload.pagination || {
          page,
          pageSize: 0,
          total: 0,
          totalPages: 0
        },
        available: true,
        capabilities
      };
    } catch (error) {
      // Let React Query render an actual error/retry state, not an empty library.
      throw error;
    }
  },

  uploadDocument: async ({ files } = {}) => {
    if (!files || files.length === 0) {
      throw new Error(translateCurrent("interfaceCopy.noFiles"));
    }

    const invalid=getInvalidRagUploadFile(files);
    if(invalid)throw Object.assign(new Error(translateCurrent("ragAssistant.errors.invalidFile")),{code:"INVALID_FILE_UPLOAD"});
    const results=await Promise.allSettled(files.map(async file=>{
      const formData=new FormData();formData.append("file",file);
      const response=await httpClient.post("/features/rag/documents",formData);
      return response.data?.data ?? response.data;
    }));
    const uploadedFiles=files.filter((_,index)=>results[index].status==='fulfilled');
    const failure=results.find(result=>result.status==='rejected');
    if(failure)throw Object.assign(failure.reason,{uploadedFiles});
    return {available:true,uploaded:true,jobDetails:results.map(result=>result.value)};
  },
  deleteDocument: async (documentId) => {
    const response=await httpClient.delete(`/features/rag/documents/${encodeURIComponent(documentId)}`);
    return response.data?.data ?? response.data;
  },
  reindexDocument:async(documentId)=>{
    const response=await httpClient.post(`/features/rag/documents/${encodeURIComponent(documentId)}/reindex`);
    return response.data?.data??response.data;
  },
  getChunkDetail: async (chunkId, signal) => {
    const response = await httpClient.get(`/features/rag/chunks/${chunkId}`, {
      signal
    });
    return response.data?.data ?? response.data;
  }
};
