import { useEffect, useRef } from 'react';
import { History, MessageSquarePlus } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';

// The frontend half of GET /rag/sessions - real, RLS-scoped conversation
// sessions (backend/src/ai/routers/rag.py), not a fixture. Kept as a small
// dropdown rather than a full sidebar/page: this is a "resume an earlier
// conversation" affordance, not a primary navigation surface.
export function RagSessionHistory({ open, onToggle, sessions, isLoading, isError, activeSessionId, onSelectSession, onNewChat, formatRelativeTime, t }) {
  const wrapRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const handleOutsideClick = (event) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target)) onToggle();
    };
    document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, [open, onToggle]);

  return (
    <div className="rag-session-history">
      <Button size="sm" variant="outline" leadingIcon={<MessageSquarePlus size={15} />} onClick={onNewChat}>
        {t('ragAssistant.history.newChat')}
      </Button>
      <div className="rag-session-history__dropdown-wrap" ref={wrapRef}>
        <Button size="sm" variant="outline" leadingIcon={<History size={15} />} onClick={onToggle} aria-expanded={open} aria-haspopup="true">
          {t('ragAssistant.history.title')}
        </Button>
        {open && (
          <div className="rag-session-history__panel" role="menu">
            {isLoading && <p className="rag-session-history__status">{t('common.loading')}</p>}
            {isError && <p className="rag-session-history__status">{t('ragAssistant.history.unavailable')}</p>}
            {!isLoading && !isError && sessions.length === 0 && (
              <p className="rag-session-history__status">{t('ragAssistant.history.empty')}</p>
            )}
            {!isLoading && !isError && sessions.map((session) => (
              <button
                type="button"
                key={session.session_id}
                role="menuitem"
                className={`rag-session-history__item ${session.session_id === activeSessionId ? 'is-active' : ''}`}
                onClick={() => onSelectSession(session.session_id)}
              >
                <span className="rag-session-history__item-title">{session.title || t('ragAssistant.history.untitled')}</span>
                <span className="rag-session-history__item-time">{formatRelativeTime(session.updated_at)}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
