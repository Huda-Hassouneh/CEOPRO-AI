import {
  ChevronLeft,
  ChevronRight,
  FileSearch,
  PanelRightClose,
  Search,
  Upload
} from "lucide-react";

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

  onPageChange,

  onUpload,
  onCollapse,
  onRetry,

  dir,
  t,
  formatDate,
  formatSize
}) {
  const documents = data?.documents || [];

  const pagination = data?.pagination || {};

  const currentPage = Math.max(1, Number(pagination.page) || 1);

  const pageSize = Math.max(
    1,
    Number(pagination.pageSize) || documents.length || 1
  );

  const total = Math.max(0, Number(pagination.total) || 0);

  const totalPages = Math.max(
    1,
    Number(pagination.totalPages) || Math.ceil(total / pageSize) || 1
  );

  const availableTypes = [
    ...new Set(documents.map((document) => document.type).filter(Boolean))
  ];

  const normalizedSearch = search.trim().toLocaleLowerCase();

  const filtered = documents
    .filter((document) => {
      const matchesSearch =
        document.name?.toLocaleLowerCase().includes(normalizedSearch) ?? false;

      const matchesType = type === "all" || document.type === type;

      return matchesSearch && matchesType;
    })
    .sort((a, b) => {
      const delta = new Date(b.uploadedAt || 0) - new Date(a.uploadedAt || 0);

      return sort === "oldest" ? -delta : delta;
    });

  const canGoPrevious = !isPending && currentPage > 1;

  const canGoNext = !isPending && currentPage < totalPages;

  /*
   * Server-side result range.
   *
   * Example:
   * page = 2
   * pageSize = 10
   *
   * start = 11
   * end   = 20
   */
  const pageStart = total > 0 ? (currentPage - 1) * pageSize + 1 : 0;

  const pageEnd =
    total > 0 ? Math.min(total, pageStart + documents.length - 1) : 0;

  const goToPage = (page) => {
    if (!onPageChange) return;

    const safePage = Math.min(totalPages, Math.max(1, page));

    if (safePage === currentPage) {
      return;
    }

    onPageChange(safePage);
  };

  /*
   * Reverse arrow direction for RTL.
   */
  const PreviousIcon = dir === "rtl" ? ChevronRight : ChevronLeft;

  const NextIcon = dir === "rtl" ? ChevronLeft : ChevronRight;

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

      {!isPending && !isError && total > 0 && (
        <footer>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "8px"
            }}
          >
            <Button
              size="sm"
              variant="ghost"
              disabled={!canGoPrevious}
              onClick={() => goToPage(currentPage - 1)}
              aria-label={t("ragAssistant.sources.page", {
                value: currentPage - 1
              })}
              title={t("ragAssistant.sources.page", {
                value: currentPage - 1
              })}
            >
              <PreviousIcon size={16} aria-hidden="true" />
            </Button>

            <div
              style={{
                minWidth: 0,
                display: "grid",
                gap: "2px",
                textAlign: "center"
              }}
            >
              <span>
                {t("ragAssistant.documents.showing", {
                  start: pageStart,
                  end: pageEnd,
                  total
                })}
              </span>

              {totalPages > 1 && (
                <strong
                  style={{
                    color: "var(--ceopro-text-secondary)",
                    fontSize: "9px",
                    fontWeight: 700
                  }}
                >
                  {t("ragAssistant.sources.page", {
                    value: currentPage
                  })}
                  {" / "}
                  {totalPages}
                </strong>
              )}
            </div>

            <Button
              size="sm"
              variant="ghost"
              disabled={!canGoNext}
              onClick={() => goToPage(currentPage + 1)}
              aria-label={t("ragAssistant.sources.page", {
                value: currentPage + 1
              })}
              title={t("ragAssistant.sources.page", {
                value: currentPage + 1
              })}
            >
              <NextIcon size={16} aria-hidden="true" />
            </Button>
          </div>
        </footer>
      )}
    </aside>
  );
}
