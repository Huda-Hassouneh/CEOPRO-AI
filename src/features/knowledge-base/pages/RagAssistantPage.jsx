import { useMemo, useState } from "react";
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
import { KnowledgeBasePanel } from "../components/KnowledgeBasePanel.jsx";
import { useKnowledgeDocuments } from "../hooks/useKnowledgeDocuments.js";
import { useDocumentUpload } from "../hooks/useDocumentUpload.js";
import { useRagChat } from "../hooks/useRagChat.js";
import { FeatureGate } from "../../billing/components/FeatureGate.jsx";
import "../../data-ingestion/styles/DataIngestion.css";
import "../styles/RagAssistant.css";

const createMessageId = () =>
  globalThis.crypto?.randomUUID?.() || `message-${Date.now()}`;

export function RagAssistantPage() {
  const { t, locale, dir } = useI18n();
  const companyId = useAuthStore((state) => state.tenantId);
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
  const [requestError, setRequestError] = useState(false);
  const documentsQuery = useKnowledgeDocuments({
    companyId,
    search,
    type,
    sort,
    page: 1
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
      ? `${sizeFormatter.format(bytes / 1024)} KB`
      : `${sizeFormatter.format(bytes / (1024 * 1024))} MB`;

  const submitQuestion = async (content, attachments) => {
    const createdAt = new Date().toISOString();
    setMessages((current) => [
      ...current,
      {
        messageId: createMessageId(),
        role: "user",
        content,
        attachments,
        createdAt
      }
    ]);
    setQuestion("");
    setMessageAttachments([]);
    setRequestError(false);
    try {
      const result = await chatMutation.mutateAsync({
        question: content,
        attachments: attachments.map(({ file, ...metadata }) => ({
          ...metadata,
          file
        })),
        companyId
      });
      if (!result?.available || !result.message) {
        setRequestError(true);
        setNotice({
          variant: "info",
          message: t("ragAssistant.feedback.chatUnavailable")
        });
        return;
      }
      setMessages((current) => [...current, result.message]);
    } catch {
      setRequestError(true);
      setNotice({
        variant: "error",
        message: t("ragAssistant.feedback.requestFailed")
      });
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
    if (!files.length) return;
    try {
      await ingestionApi.prepareFiles(files);
      const result = await uploadMutation.mutateAsync({ files, companyId });
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
    } catch {
      setNotice({
        variant: "error",
        message: t("ragAssistant.feedback.uploadFailed")
      });
    }
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
          {requestError && (
            <div className="rag-request-error" role="alert">
              {t("ragAssistant.chat.unavailable")}
            </div>
          )}
          <RagChatWindow
            messages={messages}
            question={question}
            onQuestionChange={setQuestion}
            attachments={messageAttachments}
            onAttachmentsChange={setMessageAttachments}
            onAttachmentError={handleAttachmentError}
            onSubmit={submitQuestion}
            pending={chatMutation.isPending}
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
            onSearch={setSearch}
            type={type}
            onType={setType}
            sort={sort}
            onSort={setSort}
            onUpload={() => setUploadOpen(true)}
            onCollapse={() => setKnowledgeOpen(false)}
            onRetry={() => documentsQuery.refetch()}
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
            <FileUploadDropzone files={files} onFilesChange={setFiles} />
            <div style={{ marginTop: "var(--ceopro-space-4)" }}></div>
          </>
        </FeatureGate>
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
