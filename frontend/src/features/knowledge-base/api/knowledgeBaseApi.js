import httpClient from '../../../shared/lib/httpClient.js';
import { mapAnswer } from '../utils/references.js';

// The real backend endpoint - backend/src/ai/routers/rag.py's POST /rag/query
// (the evidence-based advisor: company records, documents, public research
// and calculations, answered claim by claim with numbered references). Chat
// itself is real; the capabilities below reflect exactly what this backend
// can and cannot do today - never claimed true if there's no real endpoint
// behind it. conversationHistory/documentPreview etc. below now also
// includes real server-side session persistence (conversation_store.py) -
// GET /rag/sessions and GET /rag/sessions/{id}/messages are real endpoints,
// not stubs.
const capabilities = Object.freeze({
  chat: true,
  streaming: false,
  conversationHistory: true,
  documentUpload: true,
  documentPreview: false,
  documentActions: false,
  messageAttachments: false,
  imageInput: false,
});

// BudgetError reason code -> ragAssistant.feedback.reasons.* key.
const BILLING_REASONS = Object.freeze({
  BUDGET_EXHAUSTED: 'creditsExhausted',
  SUBSCRIPTION_INACTIVE: 'subscriptionInactive',
  COST_NOT_CONFIGURED: 'pricingNotConfigured',
  NO_BILLING_CONTEXT: 'notConfigured',
  PROVIDER_DISABLED: 'serviceSuspended',
  PROVIDER_CAP_REACHED: 'serviceSuspended',
  CONCURRENCY_LIMIT: 'tooManyRunning',
  REQUEST_TOO_LARGE: 'tooLarge',
  ACCOUNTING_UNAVAILABLE: 'accountingUnavailable',
  DUPLICATE_REQUEST: 'internalError',
});

const createMessageId = () => globalThis.crypto?.randomUUID?.() || `message-${Date.now()}`;

export function mapDocuments(response) {
  return (response?.documents || []).map((document) => ({
    id: document.document_id,
    name: document.file_name,
    type: document.type,
    size: document.size_bytes,
    uploadedAt: document.uploaded_at,
    status: document.status,
    chunkCount: document.chunk_count,
    searchable: Boolean(document.searchable),
  }));
}

export const knowledgeBaseApi = {
  getCapabilities: async () => capabilities,

  // GET /rag/sessions - this tenant+user's own conversation sessions
  // (RLS-scoped, most recently active first).
  listSessions: async () => {
    try {
      const response = await httpClient.get('/rag/sessions');
      return { sessions: response.data?.sessions ?? [], available: true };
    } catch {
      return { sessions: [], available: false };
    }
  },

  // GET /rag/sessions/{id}/messages - full history for a page-refresh
  // restore. A 404 (session doesn't exist, or belongs to a different
  // tenant/user - RLS makes those indistinguishable, see
  // conversation_store.py::session_exists()'s own docstring) is not an
  // error to surface, just "there's nothing to restore" - the caller is
  // expected to fall back to starting a fresh session.
  getSessionMessages: async (sessionId) => {
    if (!sessionId) return { available: false, messages: [] };
    try {
      const response = await httpClient.get(`/rag/sessions/${sessionId}/messages`);
      const messages = (response.data?.messages ?? []).map((message) => ({
        messageId: message.message_id,
        role: message.role,
        ...(message.role === 'assistant' ? mapAnswer(message) : { content: message.content }),
        createdAt: message.created_at,
      }));
      return { available: true, messages };
    } catch {
      return { available: false, messages: [] };
    }
  },

  // sessionId, once known (either passed in from a prior turn, or
  // restored from GET /rag/sessions/{id}/messages on page load), is the
  // authoritative history source - the backend loads real persisted
  // history from conversation_store.py and ignores any client-supplied
  // history entirely once a session exists (routers/rag.py's own
  // docstring). Omitting sessionId starts a brand-new persisted session
  // server-side; its id comes back in the response for the caller to
  // remember for every subsequent turn.
  chat: async ({ question, sessionId, signal } = {}) => {
    if (!question?.trim()) return { available: false, message: null };
    try {
      const response = await httpClient.post('/rag/query', null, {
        params: {
          query_text: question,
          session_id: sessionId || undefined,
        },
        signal,
      });
      return {
        available: true,
        sessionId: response.data.session_id,
        message: {
          messageId: createMessageId(),
          role: 'assistant',
          ...mapAnswer(response.data),
          createdAt: new Date().toISOString(),
        },
      };
    } catch (error) {
      const failedSessionId = error?.response?.headers?.['x-assistant-session-id'] || null;
      const persistedSession = failedSessionId ? { sessionId: failedSessionId } : {};
      // A stale/invalid session id (e.g. restored from localStorage after
      // the session was deleted server-side) is a 404 - distinguish it so
      // the caller can drop the dead id and retry as a fresh session,
      // rather than surfacing a generic "chat unavailable" for a case
      // that's actually recoverable.
      if (error?.response?.status === 404) {
        return { available: false, sessionNotFound: true, ...persistedSession, message: null };
      }
      // An AI call refused before it ran by the company's AI Credits or the
      // server's provider settings (backend billing/credits.py BudgetError,
      // whose body always carries `budget`). Checked before the generic 402/
      // 503 handling below: "AI pricing isn't set up" or "credits used up"
      // must never read as "busy, try again in 30 seconds".
      const detail = error?.response?.data?.detail;
      if (detail && typeof detail === 'object' && 'budget' in detail && BILLING_REASONS[detail.reason]) {
        return { available: false, reason: BILLING_REASONS[detail.reason], renewsOn: detail.period_end || null,
          ...persistedSession, message: null };
      }
      // 503 = the assistant's language model is rate limited right now;
      // Retry-After says how long until a new question can be answered.
      // 402 = this company's plan allowance of assistant questions is used
      // up for the billing period (not an error, and not anyone else's
      // limit); detail.period_end says when it renews.
      if (error?.response?.status === 402) {
        const detail = error.response.data?.detail || {};
        return { available: false, planLimit: true, renewsOn: detail.period_end || null,
          ...persistedSession, message: null };
      }
      // 429 = this company sent many questions in the last minute;
      // 503 = the language model provider is busy for everyone.
      // X-Assistant-Reason (routers/rag.py) says why no answer was produced,
      // so the chat can tell the user the real cause.
      const reason = error?.response?.headers?.['x-assistant-reason'] || null;
      if (reason === 'cost_not_configured') {
        return { available: false, reason: 'pricingNotConfigured', ...persistedSession, message: null };
      }
      if (reason === 'not_configured') {
        return { available: false, reason: 'notConfigured', ...persistedSession, message: null };
      }
      if (error?.response?.status === 429 || error?.response?.status === 503) {
        const retryAfter = Number.parseInt(error.response.headers?.['retry-after'], 10);
        return { available: false, busy: true, retryAfterSeconds: Number.isFinite(retryAfter) ? retryAfter : null,
          ...persistedSession, message: null };
      }
      if (!error?.response) {
        return { available: false, reason: 'offline', ...persistedSession, message: null };
      }
      return {
        available: false,
        reason: reason === 'provider_unavailable' || error.response.status === 502 ? 'providerUnavailable' : 'internalError',
        ...persistedSession,
        message: null,
      };
    }
  },

  // POST /rag/documents/{id}/retry - processes a failed document again.
  retryDocument: async (documentId) => (await httpClient.post(`/rag/documents/${encodeURIComponent(documentId)}/retry`)).data,

  // GET /rag/documents - the documents this company uploaded for the
  // assistant, with their real processing status.
  listDocuments: async ({ page = 1 } = {}) => {
    const response = await httpClient.get('/rag/documents');
    const documents = mapDocuments(response.data);
    return {
      documents,
      pagination: { page, pageSize: documents.length, total: documents.length, totalPages: documents.length ? 1 : 0 },
      available: true,
      capabilities,
    };
  },

  uploadDocument: async ({ files } = {}) => {
    if (!files?.length) return { available: false, uploaded: false, files: [] };
    // Promise.allSettled, not Promise.all: each file is an independent
    // upload - one failing (a bad file, a transient network error)
    // shouldn't discard the real, already-succeeded uploads of the
    // others. `uploaded` is true if at least one file made it through;
    // `files` reports only the ones that actually did.
    const settled = await Promise.allSettled(files.map(async (fileEntry) => {
      const file = fileEntry.file || fileEntry;
      const formData = new FormData();
      formData.append('file', file);
      const response = await httpClient.post('/rag/documents/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      return { file, document: response.data };
    }));
    const uploaded = settled.filter((result) => result.status === 'fulfilled').map((result) => result.value);
    return {
      available: uploaded.length > 0,
      uploaded: uploaded.length > 0,
      files: uploaded.map((entry) => entry.file),
      documentsAdded: uploaded.filter((entry) => entry.document?.searchable).length,
      documentsProcessing: uploaded.filter((entry) => entry.document?.status === 'processing').length,
      documentsFailed: uploaded.filter((entry) => entry.document?.status === 'failed').length,
      duplicate: uploaded.filter((entry) => entry.document?.duplicate).length,
      rejected: settled.length - uploaded.length,
    };
  },
};
