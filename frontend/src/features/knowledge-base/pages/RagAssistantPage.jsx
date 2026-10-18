import { translateCurrent } from '../../../shared/lib/i18n.js';
import { useQueryClient } from "@tanstack/react-query";
import { mapRagTurns, reuseRagRequest } from "../utils/ragChatContract.js";
import { knowledgeBaseApi } from "../api/knowledgeBaseApi.js";
import { useEffect, useMemo, useRef, useState } from "react";
import { Upload } from "lucide-react";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { useAuthStore } from "../../auth/store/authStore.js";
import PageHeader from "../../../shared/components/layout/PageHeader.jsx";
import Button from "../../../shared/components/ui/Button.jsx";
import Modal from "../../../shared/components/ui/Modal.jsx";
import Toast from "../../../shared/components/ui/Toast.jsx";

import { FileUploadDropzone } from "../../data-ingestion/components/FileUploadDropzone.jsx";
import { ingestionApi } from "../../data-ingestion/api/ingestionApi.js";
import { RagChatWindow } from "../components/RagChatWindow.jsx";
import { RagSessionHeader } from "../components/RagSessionHeader.jsx";
import { KnowledgeBasePanel } from "../components/KnowledgeBasePanel.jsx";
import { useKnowledgeDocuments } from "../hooks/useKnowledgeDocuments.js";
import { useDocumentUpload } from "../hooks/useDocumentUpload.js";
import { useRagChat } from "../hooks/useRagChat.js";
import { getRagErrorFeedback } from "../utils/ragErrorFeedback.js";
import { FeatureGate } from "../../billing/components/FeatureGate.jsx";
import "../../data-ingestion/styles/DataIngestion.css";
import "../styles/RagAssistant.css";

const createMessageId = () =>
  globalThis.crypto?.randomUUID?.() ||
  "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 3) | 8).toString(16);
  });

export function RagAssistantPage() {
  const { t, locale, dir } = useI18n();
  const companyId = useAuthStore((state) => state.tenantId);
  const userId = useAuthStore(
    (state) => state.user?.userId ?? state.user?.user_id ?? state.user?.id
  );
  const [sessionId, setSessionId] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [historyError, setHistoryError] = useState(null);
  const retryRequest = useRef(null);
  const scopeRef = useRef("");
  const requestAbort = useRef(null);
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [messageAttachments, setMessageAttachments] = useState([]);
  const [search, setSearch] = useState("");
  const [type, setType] = useState("all");
  const [sort, setSort] = useState("newest");
  const [knowledgeOpen, setKnowledgeOpen] = useState(true);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [files, setFiles] = useState([]);
  const [notice, setNotice] = useState(null);
  const [requestError, setRequestError] = useState(null);
  const [page, setPage] = useState(1);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const queryClient = useQueryClient();
  const reindexDocument = async (document) => {
    if (reindexing) return;
    setReindexing(true);
    try {
      const result = await knowledgeBaseApi.reindexDocument(document.id);
      await queryClient.invalidateQueries({
        queryKey: ["knowledge-documents"]
      });
      setNotice({
        variant: result.search_state === "ready" ? "success" : "warning",
        message: t(
          result.search_state === "ready"
            ? "ragAssistant.search.finished"
            : "ragAssistant.search.notReadable"
        )
      });
    } catch (error) {
      setNotice(getRagErrorFeedback(error, { action: "documents", t, locale }));
    } finally {
      setReindexing(false);
    }
  };
  const deleteDocument = async () => {
    if (!deleteTarget || deleting) return;
    setDeleting(true);
    try {
      await knowledgeBaseApi.deleteDocument(deleteTarget.id);
      setDeleteTarget(null);
      setMessages([]);
      setSessionId(null);
      retryRequest.current = null;
      queryClient.removeQueries({ queryKey: ["rag_chunk"] });
      await queryClient.invalidateQueries({
        queryKey: ["knowledge-documents"]
      });
      await queryClient.invalidateQueries({
        queryKey: ["subscription", "usage"]
      });
      setNotice({
        variant: "success",
        message: t("ragAssistant.documents.deleted")
      });
    } catch (error) {
      setNotice({
        variant: "error",
        message: t("ragAssistant.documents.deleteFailed")
      });
    } finally {
      setDeleting(false);
    }
  };
  const documentsQuery = useKnowledgeDocuments({
    companyId,
    search,
    type,
    sort,
    page
  });
  const chatMutation = useRagChat();
  const uploadMutation = useDocumentUpload();
  const timeFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, { hour: "numeric", minute: "2-digit" }),
    [locale]
  );
  const dateFormatter = useMemo(
    () => new Intl.DateTimeFormat(locale, { dateStyle: "medium" }),
    [locale]
  );
  const sizeFormatter = useMemo(
    () => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }),
    [locale]
  );
  const formatTime = (value) => timeFormatter.format(new Date(value));
  const formatDate = (value) => dateFormatter.format(new Date(value));
  const formatSize = (bytes) =>
    bytes < 1024 * 1024
      ? `${sizeFormatter.format(bytes / 1024)} KiB`
      : `${sizeFormatter.format(bytes / (1024 * 1024))} MiB`;

  const refreshSessions = async () => {
    const scope = scopeRef.current;
    const result = await knowledgeBaseApi.listSessions();
    if (scopeRef.current === scope) setSessions(result.sessions ?? []);
  };
  const loadInitialHistory = async (signal) => {
    const scope = scopeRef.current;
    setHistoryLoading(true);
    setLoadingConversation(false);
    setHistoryError(null);
    try {
      const result = await knowledgeBaseApi.listSessions(signal);
      if (signal?.aborted || scopeRef.current !== scope) return;
      setSessions(result.sessions ?? []);
      const latest = result.sessions?.[0];
      if (latest) {
        const detail = await knowledgeBaseApi.getSession(latest.session_id, signal);
        if (signal?.aborted || scopeRef.current !== scope) return;
        setSessionId(latest.session_id);
        setMessages(mapRagTurns(detail.turns, t));
      }
    } catch (error) {
      if (scopeRef.current === scope && !signal?.aborted) {
        setHistoryError({ kind: "list" });
      }
    } finally {
      if (scopeRef.current === scope && !signal?.aborted) setHistoryLoading(false);
    }
  };
  useEffect(() => {
    const scope = `${companyId}:${userId}`;
    scopeRef.current = scope;
    const abort = new AbortController();
    setMessages([]);
    setSessionId(null);
    setSessions([]);
    setHistoryLoading(true);
    setHistoryError(null);
    setRequestError(null);
    retryRequest.current = null;
    setQuestion("");
    setMessageAttachments([]);
    setNotice(null);
    setFiles([]);
    setUploadOpen(false);
    setDeleteTarget(null);
    loadInitialHistory(abort.signal);
    return () => {
      abort.abort();
      requestAbort.current?.abort();
      scopeRef.current = "";
    };
  }, [companyId, userId]);

  const openConversation = async (id) => {
    if (historyLoading || chatMutation.isPending || (id && id === sessionId)) return;
    setHistoryLoading(true);
    setLoadingConversation(Boolean(id));
    setHistoryError(null);
    const scope = scopeRef.current;
    try {
      if (!id) {
        setRequestError(null);
        setNotice(null);
        retryRequest.current = null;
        setSessionId(null);
        setMessages([]);
        setQuestion("");
        setMessageAttachments([]);
        return;
      }
      const detail = await knowledgeBaseApi.getSession(id);
      if (scopeRef.current === scope) {
        setRequestError(null);
        setNotice(null);
        retryRequest.current = null;
        setSessionId(id);
        setMessages(mapRagTurns(detail.turns, t));
        setQuestion("");
        setMessageAttachments([]);
      }
    } catch (error) {
      if (scopeRef.current === scope)
        setHistoryError({ kind: "switch", id });
    } finally {
      if (scopeRef.current === scope) {
        setHistoryLoading(false);
        setLoadingConversation(false);
      }
    }
  };

  const submitQuestion = async (content, attachments) => {
    if (chatMutation.isPending || historyLoading) return;
    const previous = retryRequest.current;
    const requestId =
      previous?.question === content ? previous.id : createMessageId();
    const requestSessionId =
      previous?.question === content ? previous.sessionId : sessionId;
    retryRequest.current = {
      id: requestId,
      question: content,
      sessionId: requestSessionId
    };
    const createdAt = new Date().toISOString(),
      scope = scopeRef.current;
    requestAbort.current = new AbortController();
    setMessages((current) => [
      ...current.filter((m) => !m.messageId.startsWith(requestId)),
      {
        messageId: `${requestId}-user`,
        role: "user",
        content,
        attachments,
        createdAt
      }
    ]);
    setQuestion("");
    setMessageAttachments([]);
    setRequestError(null);
    setNotice(null);
    try {
      const result = await chatMutation.mutateAsync({
        question: content,
        requestId,
        sessionId: requestSessionId,
        language: locale.startsWith("ar") ? "ar" : "en",
        signal: requestAbort.current.signal,
        attachments,
        companyId
      });
      if (scopeRef.current !== scope) return;
      if (!result?.available || !result.message)
        throw new Error(translateCurrent("interfaceCopy.ragAnswerMissing"));
      retryRequest.current = null;
      setHistoryError(null);
      setSessionId(result.sessionId);
      setMessages((current) => [
        ...current.filter((m) => m.messageId !== result.message.messageId),
        result.message
      ]);
      refreshSessions().catch(() => {});
    } catch (error) {
      if (scopeRef.current !== scope) return;
      if (!reuseRagRequest(error)) retryRequest.current = null;
      const feedback = getRagErrorFeedback(error, {
        action: "chat",
        t,
        locale
      });
      setRequestError(feedback);
      setNotice(feedback);
      setQuestion(content);
      setMessageAttachments(attachments);
    }
  };

  const handleAttachmentError = (reason, name) => {
    setNotice({
      variant: "error",
      message:
        reason === "invalid"
          ? t("ragAssistant.attachments.invalid", { name })
          : t("ragAssistant.attachments.readFailed")
    });
  };

  const uploadDocuments = async () => {
    if (!files.length || uploadMutation.isPending) return;

    try {
      const result = await uploadMutation.mutateAsync({
        files,
        companyId
      });

      if (!result?.uploaded) {
        setNotice({
          variant: "info",
          message: t("ragAssistant.feedback.uploadUnavailable")
        });
        return;
      }

      setFiles([]);
      setUploadOpen(false);

      setNotice({
        variant: "success",
        message: t("ragAssistant.feedback.uploaded")
      });

      documentsQuery.refetch();
    } catch (error) {
      if (error.uploadedFiles?.length) {
        setFiles((current) =>
          current.filter((file) => !error.uploadedFiles.includes(file))
        );
        setNotice({
          variant: "warning",
          message: t("ragAssistant.upload.partial")
        });
      } else
        setNotice(getRagErrorFeedback(error, { action: "upload", t, locale }));
    }
  };
  const handleSearchChange = (value) => {
    setSearch(value);
    setPage(1);
  };

  const handleTypeChange = (value) => {
    setType(value);
    setPage(1);
  };

  const handleSortChange = (value) => {
    setSort(value);
    setPage(1);
  };
  return (
    <div className="rag-assistant-page" dir={dir}>
      <PageHeader
        title={t("ragAssistant.page.title")}
        subtitle={t("ragAssistant.page.subtitle")}
      />
      <div
        className={`rag-assistant-layout ${knowledgeOpen ? "" : "is-chat-only"}`}
      >
        <div className="rag-chat-column">
          <RagSessionHeader
            sessions={sessions}
            sessionId={sessionId}
            messages={messages}
            loading={historyLoading}
            loadingConversation={loadingConversation}
            sending={chatMutation.isPending}
            error={historyError?.kind}
            onSelect={openConversation}
            onNew={() => openConversation(null)}
            onRetry={() =>
              historyError?.kind === "switch"
                ? openConversation(historyError.id)
                : loadInitialHistory()
            }
            t={t}
          />
          {requestError && (
            <div className="rag-request-error" role="alert">
              {requestError.message}
              {retryRequest.current && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={chatMutation.isPending || historyLoading}
                  onClick={() =>
                    submitQuestion(
                      retryRequest.current.question,
                      messageAttachments
                    )
                  }
                >
                  {t("ragAssistant.history.retry")}
                </Button>
              )}
            </div>
          )}
          <RagChatWindow
            key={`${companyId}:${userId}:${sessionId ?? "new"}`}
            messages={messages}
            question={question}
            onQuestionChange={setQuestion}
            attachments={messageAttachments}
            onAttachmentsChange={setMessageAttachments}
            onAttachmentError={handleAttachmentError}
            onSubmit={submitQuestion}
            pending={chatMutation.isPending}
            disabled={historyLoading}
            t={t}
            formatTime={formatTime}
            formatSize={formatSize}
            knowledgeOpen={knowledgeOpen}
            onOpenKnowledge={() => setKnowledgeOpen(true)}
          />
        </div>
        {knowledgeOpen && (
          <KnowledgeBasePanel
            data={documentsQuery.data}
            isPending={documentsQuery.isPending}
            isError={documentsQuery.isError}
            search={search}
            onSearch={handleSearchChange}
            type={type}
            onType={handleTypeChange}
            sort={sort}
            onSort={handleSortChange}
            onPageChange={setPage}
            onUpload={() => setUploadOpen(true)}
            onDelete={chatMutation.isPending ? undefined : setDeleteTarget}
            deleting={deleting || reindexing}
            onReindex={chatMutation.isPending ? undefined : reindexDocument}
            reindexing={reindexing}
            onCollapse={() => setKnowledgeOpen(false)}
            onRetry={() => documentsQuery.refetch()}
            dir={dir}
            t={t}
            formatDate={formatDate}
            formatSize={formatSize}
          />
        )}
      </div>

      <Modal
        isOpen={uploadOpen}
        onClose={() => setUploadOpen(false)}
        title={t("ragAssistant.upload.title")}
        closeLabel={t("common.close")}
        maxWidth="680px"
        footer={
          <>
            <Button variant="outline" onClick={() => setUploadOpen(false)}>
              {t("ragAssistant.actions.cancel")}
            </Button>
            <Button
              leadingIcon={<Upload size={15} />}
              disabled={!files.length}
              loading={uploadMutation.isPending}
              loadingLabel={t("ragAssistant.upload.uploading")}
              onClick={uploadDocuments}
            >
              {t("ragAssistant.knowledge.upload")}
            </Button>
          </>
        }
      >
        <p className="rag-upload-copy">
          {t("ragAssistant.upload.description")}
        </p>
        <FeatureGate featureCode="document_extraction" mode="consume" compact>
          <>
            <FileUploadDropzone
              kind="rag"
              disabled={uploadMutation.isPending}
              files={files}
              onFilesChange={setFiles}
            />
            <div style={{ marginTop: "var(--ceopro-space-4)" }}></div>
          </>
        </FeatureGate>
      </Modal>
      <Modal
        isOpen={Boolean(deleteTarget)}
        onClose={() => {
          if (!deleting) setDeleteTarget(null);
        }}
        title={t("ragAssistant.documents.deleteTitle")}
        closeLabel={t("common.close")}
        footer={
          <>
            <Button
              variant="outline"
              disabled={deleting}
              onClick={() => setDeleteTarget(null)}
            >
              {t("common.cancel")}
            </Button>
            <Button loading={deleting} onClick={deleteDocument}>
              {t("ragAssistant.documents.deleteAction")}
            </Button>
          </>
        }
      >
        <p>
          {t("ragAssistant.documents.deleteConfirm", {
            name: deleteTarget?.name
          })}
        </p>
      </Modal>
      {notice && (
        <div className="rag-toast">
          <Toast
            variant={notice.variant}
            message={notice.message}
            onClose={() => setNotice(null)}
          />
        </div>
      )}
    </div>
  );
}
