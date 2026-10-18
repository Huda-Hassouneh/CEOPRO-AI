import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { useAuthStore } from "../../auth/store/authStore.js";
import PageHeader from "../../../shared/components/layout/PageHeader.jsx";
import Modal from "../../../shared/components/ui/Modal.jsx";
import Button from "../../../shared/components/ui/Button.jsx";
import Toast from "../../../shared/components/ui/Toast.jsx";
import { KnowledgeBasePanel } from "../components/KnowledgeBasePanel.jsx";
import { useKnowledgeDocuments } from "../hooks/useKnowledgeDocuments.js";
import { knowledgeBaseApi } from "../api/knowledgeBaseApi.js";
import "../styles/RagAssistant.css";

// Retained-file management stays accessible after cancellation or downgrade.
// It grants no chat/upload entitlement; the backend still authenticates membership.
export function RagKnowledgeBasePage() {
  const { t, locale, dir } = useI18n();
  const companyId = useAuthStore((s) => s.tenantId);
  const [page, setPage] = useState(1),
    [search, setSearch] = useState(""),
    [type, setType] = useState("all"),
    [sort, setSort] = useState("newest");
  const [target, setTarget] = useState(null),
    [notice, setNotice] = useState(null);
  const query = useKnowledgeDocuments({ companyId, page, search, type, sort }),
    client = useQueryClient();
  const deletion = useMutation({
    mutationFn: () => knowledgeBaseApi.deleteDocument(target.id),
    onSuccess: async () => {
      setTarget(null);
      await client.invalidateQueries({ queryKey: ["knowledge-documents"] });
      await client.invalidateQueries({ queryKey: ["subscription", "usage"] });
      setNotice({
        variant: "success",
        message: t("ragAssistant.documents.deleted")
      });
    },
    onError: () =>
      setNotice({
        variant: "error",
        message: t("ragAssistant.documents.deleteFailed")
      })
  });
  const formatSize = (bytes) =>
    `${new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(bytes / 1048576)} MiB`;
  return (
    <div className="rag-assistant-page" dir={dir}>
      <PageHeader
        title={t("ragAssistant.knowledge.title")}
        subtitle={t("ragAssistant.storage.manageDescription")}
      />
      <KnowledgeBasePanel
        data={query.data}
        isPending={query.isPending}
        isError={query.isError}
        search={search}
        onSearch={(v) => {
          setSearch(v);
          setPage(1);
        }}
        type={type}
        onType={(v) => {
          setType(v);
          setPage(1);
        }}
        sort={sort}
        onSort={setSort}
        onPageChange={setPage}
        onDelete={setTarget}
        deleting={deletion.isPending}
        onRetry={() => query.refetch()}
        dir={dir}
        t={t}
        formatDate={(value) =>
          new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(
            new Date(value)
          )
        }
        formatSize={formatSize}
      />
      <Modal
        isOpen={Boolean(target)}
        onClose={() => {
          if (!deletion.isPending) setTarget(null);
        }}
        title={t("ragAssistant.documents.deleteTitle")}
        footer={
          <>
            <Button
              disabled={deletion.isPending}
              onClick={() => setTarget(null)}
            >
              {t("common.cancel")}
            </Button>
            <Button
              loading={deletion.isPending}
              onClick={() => deletion.mutate()}
            >
              {t("ragAssistant.documents.deleteAction")}
            </Button>
          </>
        }
      >
        <p>
          {t("ragAssistant.documents.deleteConfirm", { name: target?.name })}
        </p>
      </Modal>
      {notice && (
        <Toast
          variant={notice.variant}
          message={notice.message}
          onClose={() => setNotice(null)}
        />
      )}
    </div>
  );
}
