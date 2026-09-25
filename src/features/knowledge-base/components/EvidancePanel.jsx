import { X, FileText, Loader2, AlertCircle } from "lucide-react";

export function EvidencePanel({ chunkData, isLoading, isError, onClose, t }) {
  return (
    <aside
      className="rag-evidence-panel"
      aria-label={t("ragAssistant.evidence.label") || "Citation Details"}
    >
      <header>
        <h4>{t("ragAssistant.evidence.title") || "Citation Details"}</h4>
        <button onClick={onClose} aria-label={t("common.close") || "Close"}>
          <X size={16} />
        </button>
      </header>

      <div className="rag-evidence-panel__content">
        {isLoading && (
          <div className="rag-evidence-state">
            <Loader2 className="rag-spinner" size={24} />
            <p>
              {t("ragAssistant.evidence.loading") ||
                "Loading source document..."}
            </p>
          </div>
        )}

        {isError && (
          <div className="rag-evidence-state is-error">
            <AlertCircle size={24} />
            <p>
              {t("ragAssistant.evidence.error") ||
                "Could not load source document."}
            </p>
          </div>
        )}

        {!isLoading && !isError && chunkData && (
          <>
            <div className="rag-evidence-meta">
              <FileText size={16} className="rag-evidence-icon" />
              <div>
                <span>
                  {t("ragAssistant.evidence.document") || "Document"}:
                </span>
                <strong>{chunkData.file_name}</strong>
              </div>
            </div>
            <blockquote className="rag-evidence-quote">
              {chunkData.text_content}
            </blockquote>
          </>
        )}
      </div>
    </aside>
  );
}
