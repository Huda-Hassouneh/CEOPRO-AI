const unavailableCapabilities = Object.freeze({
  chat: false,
  streaming: false,
  conversationHistory: false,
  documentUpload: false,
  documentPreview: false,
  documentActions: false,
  messageAttachments: false,
  imageInput: false,
});

// Integration boundary for the RAG service. This repository currently has no
// backend endpoints, so no prompts, answers, citations, or uploads are faked.
export const knowledgeBaseApi = {
  getCapabilities: async () => unavailableCapabilities,
  listSessions: async () => ({ sessions: [], available: false }),
  chat: async ({ question, attachments = [], companyId, signal } = {}) => {
    void question;
    void attachments;
    void companyId;
    void signal;
    return { available: false, message: null };
  },
  listDocuments: async ({ companyId, search = '', type = 'all', sort = 'newest', page = 1 } = {}) => {
    void companyId;
    void search;
    void type;
    void sort;
    return {
      documents: [],
      pagination: { page, pageSize: 0, total: 0, totalPages: 0 },
      available: false,
      capabilities: unavailableCapabilities,
    };
  },
  uploadDocument: async ({ files, companyId } = {}) => {
    void companyId;
    return { available: false, uploaded: false, files: files || [] };
  },
};
