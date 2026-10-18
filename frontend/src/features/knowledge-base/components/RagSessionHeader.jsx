import { useId } from "react";
import { AlertCircle, ChevronDown, History, LoaderCircle, MessageSquare, Plus } from "lucide-react";
import Button from "../../../shared/components/ui/Button.jsx";

export function RagSessionHeader({
  sessions,
  sessionId,
  messages,
  loading,
  loadingConversation,
  sending,
  error,
  onSelect,
  onNew,
  onRetry,
  t
}) {
  const selectId = useId();
  const selected = sessions.find((session) => session.session_id === sessionId);
  const activeTitle = sessionId
    ? selected?.title?.trim() ||
      messages.find((message) => message.role === "user")?.content?.trim() ||
      t("ragAssistant.history.untitled")
    : t("ragAssistant.history.new");
  const isEmpty = !loading && !error && sessions.length === 0 && !sessionId;
  const disabled = loading || sending;

  return (
    <section className="rag-session-header" aria-label={t("ragAssistant.history.header")}>
      <div className="rag-session-header__main">
        <div className="rag-session-header__current">
          <span className="rag-session-header__icon" aria-hidden="true">
            <MessageSquare size={19} />
          </span>
          <div className="rag-session-header__identity">
            <span className="rag-session-header__eyebrow">
              {t("ragAssistant.history.active")}
            </span>
            <strong className="rag-session-header__title" title={activeTitle} dir="auto" aria-live="polite">
              {activeTitle}
            </strong>
            {isEmpty && <small>{t("ragAssistant.history.empty")}</small>}
          </div>
        </div>

        <div className="rag-session-header__actions">
          <div className="rag-session-header__picker">
            <label htmlFor={selectId}>{t("ragAssistant.history.switch")}</label>
            <div className="rag-session-header__select-wrap">
              <History size={17} aria-hidden="true" />
              <select
                id={selectId}
                value={sessionId ?? ""}
                disabled={disabled || (sessions.length === 0 && !sessionId)}
                onChange={(event) => onSelect(event.target.value || null)}
                aria-describedby={error ? `${selectId}-feedback` : undefined}
              >
                <option value="">
                  {loading && !sessionId
                    ? t("ragAssistant.history.loadingList")
                    : error === "list" && sessions.length === 0 && !sessionId
                      ? t("ragAssistant.history.historyUnavailable")
                    : sessions.length === 0 && !sessionId
                      ? t("ragAssistant.history.noHistory")
                      : t("ragAssistant.history.new")}
                </option>
                {sessionId && !selected && (
                  <option value={sessionId}>{activeTitle}</option>
                )}
                {sessions.map((session) => (
                  <option key={session.session_id} value={session.session_id}>
                    {session.title?.trim() || t("ragAssistant.history.untitled")}
                  </option>
                ))}
              </select>
              <ChevronDown size={16} aria-hidden="true" />
            </div>
          </div>
          <Button
            size="sm"
            variant="outline"
            className="rag-session-header__new"
            leadingIcon={<Plus size={17} />}
            disabled={disabled}
            onClick={onNew}
          >
            {t("ragAssistant.history.new")}
          </Button>
        </div>
      </div>
      {loading && (
        <p className="rag-session-header__feedback" role="status">
          <LoaderCircle size={16} className="rag-session-header__spinner" aria-hidden="true" />
          {t(loadingConversation ? "ragAssistant.history.loading" : "ragAssistant.history.loadingList")}
        </p>
      )}
      {error && !loading && (
        <div className="rag-session-header__feedback is-error" id={`${selectId}-feedback`} role="alert">
          <AlertCircle size={17} aria-hidden="true" />
          <span>{t(error === "switch" ? "ragAssistant.history.openFailed" : "ragAssistant.history.loadFailed")}</span>
          <Button size="sm" variant="outline" disabled={sending} onClick={onRetry}>
            {t("ragAssistant.history.retryLoad")}
          </Button>
        </div>
      )}
    </section>
  );
}
