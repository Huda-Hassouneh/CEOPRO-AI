import { FileSearch, PanelRightClose, Search, Upload } from "lucide-react";
import Button from "../../../shared/components/ui/Button.jsx";
import EmptyState from "../../../shared/components/ui/EmptyState.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import { KnowledgeBaseDocumentRow } from "./KnowledgeBaseDocumentRow.jsx";

export function KnowledgeBasePanel({
  data,
  isPending,
  isError,
  search,
  onSearch,
  type,
  onType,
  sort,
  onSort,
  onUpload,
  onCollapse,
  onRetry,
  t,
  formatDate,
  formatSize
}) {
  const documents = data?.documents || [];
  const availableTypes = [
    ...new Set(documents.map((document) => document.type).filter(Boolean))
  ];
  const filtered = documents
    .filter((document) => {
      const matchesSearch = document.name
        ?.toLocaleLowerCase()
        .includes(search.trim().toLocaleLowerCase());
      return matchesSearch && (type === "all" || document.type === type);
    })
    .sort((a, b) => {
      const delta = new Date(b.uploadedAt || 0) - new Date(a.uploadedAt || 0);
      return sort === "oldest" ? -delta : delta;
    });

  return (
    <aside className="rag-knowledge-panel" aria-labelledby="rag-kb-title">
      <header className="rag-knowledge-panel__header">
        <div>
          <h2 id="rag-kb-title">{t("ragAssistant.knowledge.title")}</h2>
          <p>{t("ragAssistant.knowledge.subtitle")}</p>
        </div>
        <button
          type="button"
          onClick={onCollapse}
          aria-label={t("ragAssistant.knowledge.collapse")}
        >
          <PanelRightClose size={18} />
        </button>
      </header>
      <Button
        size="sm"
        fullWidth
        leadingIcon={<Upload size={15} />}
        onClick={onUpload}
      >
        {t("ragAssistant.knowledge.upload")}
      </Button>
      <div className="rag-document-controls">
        <label className="rag-document-search">
          <Search size={15} aria-hidden="true" />
          <input
            type="search"
            value={search}
            onChange={(event) => onSearch(event.target.value)}
            placeholder={t("ragAssistant.knowledge.search")}
            aria-label={t("ragAssistant.knowledge.search")}
          />
        </label>
        <div>
          <label>
            <span>{t("ragAssistant.knowledge.type")}</span>
            <select
              value={type}
              onChange={(event) => onType(event.target.value)}
            >
              <option value="all">
                {t("ragAssistant.knowledge.allTypes")}
              </option>
              {availableTypes.map((value) => (
                <option key={value} value={value}>
                  {value.toLocaleUpperCase()}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>{t("ragAssistant.knowledge.sort")}</span>
            <select
              value={sort}
              onChange={(event) => onSort(event.target.value)}
            >
              <option value="newest">
                {t("ragAssistant.knowledge.newest")}
              </option>
              <option value="oldest">
                {t("ragAssistant.knowledge.oldest")}
              </option>
            </select>
          </label>
        </div>
      </div>
      <div className="rag-document-list">
        {isPending && (
          <div className="rag-document-skeletons" aria-busy="true">
            {[0, 1, 2].map((item) => (
              <Skeleton key={item} height="68px" variant="rectangular" />
            ))}
          </div>
        )}
        {isError && (
          <EmptyState
            icon={<FileSearch size={25} />}
            title={t("ragAssistant.documents.errorTitle")}
            description={t("ragAssistant.documents.errorDescription")}
            action={
              <Button size="sm" variant="outline" onClick={onRetry}>
                {t("ragAssistant.actions.retry")}
              </Button>
            }
          />
        )}
        {!isPending && !isError && filtered.length > 0 && (
          <ul>
            {filtered.map((document) => (
              <KnowledgeBaseDocumentRow
                key={document.id}
                document={document}
                t={t}
                formatDate={formatDate}
                formatSize={formatSize}
                actions={
                  data?.capabilities?.documentActions ? document.actions : []
                }
              />
            ))}
          </ul>
        )}
        {!isPending && !isError && filtered.length === 0 && (
          <EmptyState
            icon={<FileSearch size={25} />}
            title={
              search || type !== "all"
                ? t("ragAssistant.documents.noMatchesTitle")
                : t("ragAssistant.documents.emptyTitle")
            }
            description={
              search || type !== "all"
                ? t("ragAssistant.documents.noMatchesDescription")
                : t("ragAssistant.documents.emptyDescription")
            }
          />
        )}
      </div>
      {data?.pagination?.total > 0 && (
        <footer>
          {t("ragAssistant.documents.showing", {
            start: filtered.length ? 1 : 0,
            end: filtered.length,
            total: data.pagination.total
          })}
        </footer>
      )}
    </aside>
  );
}
