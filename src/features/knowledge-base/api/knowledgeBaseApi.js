import httpClient from "../../../shared/lib/httpClient.js";

const capabilities = Object.freeze({
  chat: true,
  streaming: false,
  conversationHistory: false,
  documentUpload: true, // Updated to enable upload functionality
  documentPreview: false,
  documentActions: false,
  messageAttachments: false,
  imageInput: false
});

const createMessageId = () =>
  globalThis.crypto?.randomUUID?.() || `assistant-${Date.now()}`;

export const knowledgeBaseApi = {
  getCapabilities: async () => capabilities,
  listSessions: async () => ({ sessions: [], available: false }),

  chat: async ({ question, attachments = [], signal } = {}) => {
    if (!question?.trim()) throw new Error("A question is required.");
    if (attachments.length) {
      const error = new Error(
        "Chat attachments are not supported by the current backend RAG endpoint."
      );
      error.code = "BACKEND_CAPABILITY_UNAVAILABLE";
      throw error;
    }
    console.log("yea");

    const response = await httpClient.post(
      "/features/rag/query",
      {},
      {
        params: { query_text: question.trim(), top_k: 5 },
        signal
      }
    );
    // frontend/src/features/knowledge-base/api/knowledgeBaseApi.js

    // ... inside your chat function ...

    const payload = response.data?.data ?? response.data;

    // Map the backend source shape to the frontend expected shape
    const formattedSources = Array.isArray(payload?.sources)
      ? payload.sources.map((source) => ({
          documentId: source.chunk_id, // Required for the item to be clickable
          name: `Source Document ${source.source_index}`, // Required for text to show up
          score: source.score
        }))
      : [];

    return {
      available: true,
      message: {
        messageId: createMessageId(),
        role: "assistant",
        content: payload?.answer ?? "",
        sources: formattedSources, // Pass the newly mapped array here
        createdAt: new Date().toISOString()
      }
    };
  },

  // frontend/src/features/knowledge-base/api/knowledgeBaseApi.js

  listDocuments: async ({ page = 1 } = {}) => {
    try {
      const response = await httpClient.get("/features/rag/documents", {
        params: { page }
      });

      const payload = response.data?.data ?? response.data;
      console.log({ payload });
      const mappedDocuments = (payload.documents || []).map((doc) => ({
        id: doc.document_id,
        name: doc.file_name,
        type: doc.content_type,
        uploadedAt: doc.uploaded_at,
        size: Number(doc.file_size_bytes), // Convert string back to number for formatSize
        status: "active" // Default status since it's not in the schema
      }));

      return {
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
      console.error("Failed to fetch documents:", error);
      return {
        documents: [],
        pagination: { page, pageSize: 0, total: 0, totalPages: 0 },
        available: false,
        capabilities
      };
    }
  },

  uploadDocument: async ({ files } = {}) => {
    if (!files || files.length === 0) {
      throw new Error("No files provided for upload.");
    }

    // Map each file to an individual upload promise
    const uploadPromises = files.map(async (file) => {
      // Validate the 10 MB limit per file
      if (file.size > 10 * 1024 * 1024) {
        throw new Error(`File ${file.name} exceeds the 10 MB size limit.`);
      }

      const formData = new FormData();
      formData.append("file", file); // Must be "file"[cite: 4]

      const response = await httpClient.post(
        "/features/extraction/upload",
        formData,
        {
          headers: {
            "Content-Type": "multipart/form-data"
          }
        }
      );

      return response.data?.data ?? response.data;
    });

    // Wait for all individual file uploads to finish
    const results = await Promise.all(uploadPromises);

    return {
      available: true,
      uploaded: true,
      // Returns an array of job outcomes (one per file uploaded)
      jobDetails: results
    };
  },
  getChunkDetail: async (chunkId, signal) => {
    const response = await httpClient.get(`/features/rag/chunks/${chunkId}`, {
      signal
    });
    return response.data?.data ?? response.data;
  }
};
