import { useEffect, useMemo, useState } from 'react';
import { Upload } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../../auth/store/authStore.js';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import Modal from '../../../shared/components/ui/Modal.jsx';
import Toast from '../../../shared/components/ui/Toast.jsx';
import { FileUploadDropzone } from '../../data-ingestion/components/FileUploadDropzone.jsx';
import { RagChatWindow } from '../components/RagChatWindow.jsx';
import { KnowledgeBasePanel } from '../components/KnowledgeBasePanel.jsx';
import { useKnowledgeDocuments } from '../hooks/useKnowledgeDocuments.js';
import { useDocumentUpload } from '../hooks/useDocumentUpload.js';
import { useRagChat } from '../hooks/useRagChat.js';
import { knowledgeBaseApi } from '../api/knowledgeBaseApi.js';
import '../../data-ingestion/styles/DataIngestion.css';
import '../styles/RagAssistant.css';

const createMessageId = () => globalThis.crypto?.randomUUID?.() || `message-${Date.now()}`;

// Per-viewer convenience only (which conversation to resume) - the real
// security/durability boundary is the server (conversation_sessions,
// RLS-scoped). Losing this key (private window, cleared site data) just
// means the next message starts a fresh session, never data loss server-side.
const sessionStorageKey = (companyId) => `ceopro.rag-assistant.session-id.${companyId || 'anonymous'}`;

function readStoredSessionId(companyId) {
  try {
    return localStorage.getItem(sessionStorageKey(companyId)) || null;
  } catch {
    return null;
  }
}

function writeStoredSessionId(companyId, sessionId) {
  try {
    if (sessionId) localStorage.setItem(sessionStorageKey(companyId), sessionId);
    else localStorage.removeItem(sessionStorageKey(companyId));
  } catch {
    // Best-effort only - a failing localStorage (private window, quota)
    // must never break the chat itself.
  }
}

export function RagAssistantPage() {
  const { t, locale, dir } = useI18n();
  const companyId = useAuthStore((state) => state.tenantId);
  const [messages, setMessages] = useState([]);
  const [sessionId, setSessionId] = useState(null);
  const [restoring, setRestoring] = useState(false);
  const [question, setQuestion] = useState('');
  const [search, setSearch] = useState('');
  const [type, setType] = useState('all');
  const [sort, setSort] = useState('newest');
  const [knowledgeOpen, setKnowledgeOpen] = useState(true);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [files, setFiles] = useState([]);
  const [notice, setNotice] = useState(null);
  const [requestError, setRequestError] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [sessions, setSessions] = useState([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessionsError, setSessionsError] = useState(false);
  const [switchingSession, setSwitchingSession] = useState(false);
  const documentsQuery = useKnowledgeDocuments({ companyId, search, type, sort, page: 1 });
  const chatMutation = useRagChat();
  const uploadMutation = useDocumentUpload();

  // Restore the last active session on mount / when the signed-in tenant
  // changes - this is what makes conversation history survive a page
  // refresh or a brand-new browser tab, not just local React state. A
  // stale id (session deleted, or belongs to a browser profile that since
  // logged into a different tenant) comes back as "not available" from
  // getSessionMessages - treated as "nothing to restore", not an error.
  useEffect(() => {
    let cancelled = false;
    const storedSessionId = readStoredSessionId(companyId);
    if (!storedSessionId) return undefined;
    setRestoring(true);
    knowledgeBaseApi.getSessionMessages(storedSessionId).then((result) => {
      if (cancelled) return;
      if (result.available && result.messages.length) {
        setSessionId(storedSessionId);
        setMessages(result.messages);
      } else {
        writeStoredSessionId(companyId, null);
      }
    }).finally(() => {
      if (!cancelled) setRestoring(false);
    });
    return () => { cancelled = true; };
  }, [companyId]);
  const timeFormatter = useMemo(() => new Intl.DateTimeFormat(locale, { hour: 'numeric', minute: '2-digit' }), [locale]);
  const dateFormatter = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }), [locale]);
  const sizeFormatter = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  const relativeTimeFormatter = useMemo(() => new Intl.RelativeTimeFormat(locale, { numeric: 'auto' }), [locale]);
  const formatTime = (value) => timeFormatter.format(new Date(value));
  const formatDate = (value) => dateFormatter.format(new Date(value));
  const formatSize = (bytes) => bytes < 1024 * 1024 ? `${sizeFormatter.format(bytes / 1024)} KB` : `${sizeFormatter.format(bytes / (1024 * 1024))} MB`;
  const formatRelativeTime = (value) => {
    const diffMinutes = Math.round((new Date(value).getTime() - Date.now()) / 60000);
    if (Math.abs(diffMinutes) < 60) return relativeTimeFormatter.format(diffMinutes, 'minute');
    const diffHours = Math.round(diffMinutes / 60);
    if (Math.abs(diffHours) < 24) return relativeTimeFormatter.format(diffHours, 'hour');
    return relativeTimeFormatter.format(Math.round(diffHours / 24), 'day');
  };

  const toggleHistory = () => {
    const opening = !historyOpen;
    setHistoryOpen(opening);
    if (!opening) return;
    setSessionsLoading(true);
    setSessionsError(false);
    knowledgeBaseApi.listSessions().then((result) => {
      if (!result.available) {
        setSessionsError(true);
        return;
      }
      setSessions(result.sessions);
    }).finally(() => setSessionsLoading(false));
  };

  const startNewChat = () => {
    setSessionId(null);
    setMessages([]);
    setRequestError(false);
    writeStoredSessionId(companyId, null);
    setHistoryOpen(false);
  };

  const selectSession = async (targetSessionId) => {
    if (targetSessionId === sessionId) {
      setHistoryOpen(false);
      return;
    }
    setSwitchingSession(true);
    const result = await knowledgeBaseApi.getSessionMessages(targetSessionId);
    setSwitchingSession(false);
    setHistoryOpen(false);
    if (!result.available) {
      setNotice({ variant: 'error', message: t('ragAssistant.history.loadFailed') });
      return;
    }
    setSessionId(targetSessionId);
    setMessages(result.messages);
    setRequestError(false);
    writeStoredSessionId(companyId, targetSessionId);
  };

  const submitQuestion = async (content) => {
    const createdAt = new Date().toISOString();
    setMessages((current) => [...current, { messageId: createMessageId(), role: 'user', content, createdAt }]);
    setQuestion('');
    setRequestError(false);
    try {
      const result = await chatMutation.mutateAsync({ question: content, sessionId, companyId });
      if (!result?.available || !result.message) {
        // A 404 on a session id this page already believed was live means
        // it was deleted/invalidated server-side since restore - drop it
        // so the next attempt starts a fresh session instead of repeating
        // the same 404 forever.
        if (result?.sessionNotFound) {
          setSessionId(null);
          writeStoredSessionId(companyId, null);
        }
        // The banner states the real reason no answer came back.
        setRequestError(result?.planLimit
          ? t('ragAssistant.feedback.planLimit', { date: result.renewsOn ? new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(new Date(result.renewsOn)) : '—' })
          : result?.busy
            ? t('ragAssistant.feedback.busy', { seconds: result.retryAfterSeconds ?? 30 })
            : result?.reason
              ? t(`ragAssistant.feedback.reasons.${result.reason}`)
              : t('ragAssistant.chat.unavailable'));
        return;
      }
      if (result.sessionId && result.sessionId !== sessionId) {
        setSessionId(result.sessionId);
        writeStoredSessionId(companyId, result.sessionId);
      }
      setMessages((current) => [...current, result.message]);
    } catch {
      setRequestError(t('ragAssistant.feedback.reasons.internalError'));
    }
  };

  const uploadDocuments = async () => {
    if (!files.length) return;
    try {
      // One upload per file. This used to call ingestionApi.prepareFiles()
      // AND uploadDocument() - both POST /extraction/upload - so every
      // document (and any spreadsheet's sales rows) was imported twice.
      const result = await uploadMutation.mutateAsync({ files, companyId });
      if (!result?.uploaded) {
        setNotice({ variant: 'error', message: t('ragAssistant.feedback.uploadFailed') });
        return;
      }
      setFiles([]);
      setUploadOpen(false);
      const problems = result.documentsFailed + result.rejected;
      setNotice({
        variant: problems ? 'warning' : 'success',
        message: t('ragAssistant.feedback.uploadSummary', {
          added: result.documentsAdded, data: result.importedAsData, failed: problems,
        }),
      });
      documentsQuery.refetch();
    } catch {
      setNotice({ variant: 'error', message: t('ragAssistant.feedback.uploadFailed') });
    }
  };

  return <div className="rag-assistant-page" dir={dir}>
    <PageHeader title={t('ragAssistant.page.title')} subtitle={t('ragAssistant.page.subtitle')} />
    <div className={`rag-assistant-layout ${knowledgeOpen ? '' : 'is-chat-only'}`}>
      <div className="rag-chat-column">
        {requestError && <div className="rag-request-error" role="alert">{typeof requestError === 'string' ? requestError : t('ragAssistant.chat.unavailable')}</div>}
        <RagChatWindow messages={messages} question={question} onQuestionChange={setQuestion} onSubmit={submitQuestion} pending={chatMutation.isPending} restoring={restoring || switchingSession} t={t} locale={locale} dir={dir} formatTime={formatTime} formatSize={formatSize} knowledgeOpen={knowledgeOpen} onOpenKnowledge={() => setKnowledgeOpen(true)} sessionHistoryProps={{ open: historyOpen, onToggle: toggleHistory, sessions, isLoading: sessionsLoading, isError: sessionsError, activeSessionId: sessionId, onSelectSession: selectSession, onNewChat: startNewChat, formatRelativeTime }} />
      </div>
      {knowledgeOpen && <KnowledgeBasePanel data={documentsQuery.data} isPending={documentsQuery.isPending} isError={documentsQuery.isError} search={search} onSearch={setSearch} type={type} onType={setType} sort={sort} onSort={setSort} onUpload={() => setUploadOpen(true)} onCollapse={() => setKnowledgeOpen(false)} onRetry={() => documentsQuery.refetch()} t={t} formatDate={formatDate} formatSize={formatSize} />}
    </div>

    <Modal isOpen={uploadOpen} onClose={() => setUploadOpen(false)} title={t('ragAssistant.upload.title')} closeLabel={t('common.close')} maxWidth="680px" footer={<><Button variant="outline" onClick={() => setUploadOpen(false)}>{t('ragAssistant.actions.cancel')}</Button><Button leadingIcon={<Upload size={15} />} disabled={!files.length} loading={uploadMutation.isPending} loadingLabel={t('ragAssistant.upload.uploading')} onClick={uploadDocuments}>{t('ragAssistant.knowledge.upload')}</Button></>}>
      <p className="rag-upload-copy">{t('ragAssistant.upload.description')}</p>
      <FileUploadDropzone files={files} onFilesChange={setFiles} />
    </Modal>
    {notice && <div className="rag-toast"><Toast variant={notice.variant} message={notice.message} onClose={() => setNotice(null)} /></div>}
  </div>;
}
