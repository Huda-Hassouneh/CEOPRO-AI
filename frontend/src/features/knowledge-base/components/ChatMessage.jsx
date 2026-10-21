import { useCallback, useRef, useState } from 'react';
import { Bot, FileSearch, Info, UserRound } from 'lucide-react';
import { AssistantResponse } from './AssistantResponse.jsx';
import { AnswerReferences } from './AnswerReferences.jsx';
import { CalculationCard } from './CalculationCard.jsx';
import { MessageAttachments } from './MessageAttachments.jsx';
import { ReferencePanel } from './ReferencePanel.jsx';
import { referenceByNumber, statusNotes } from '../utils/references.js';

export function ChatMessage({ message, t, formatTime, formatSize, locale, dir, onAsk }) {
  const isUser = message.role === 'user';
  const [activeRef, setActiveRef] = useState(null);
  const opener = useRef(null);
  const references = message.references || [];
  const openRef = useCallback((n, trigger) => {
    if (trigger) opener.current = trigger;
    setActiveRef(n);
  }, []);
  const closeRef = useCallback(() => {
    setActiveRef(null);
    opener.current?.focus?.();
  }, []);
  const notes = isUser ? [] : statusNotes(message.evidenceStatus);
  const offline = message.answerMode === 'evidence' || message.answerMode === 'unverifiable' || message.answerMode === 'unlinked';

  return <article className={`rag-message is-${isUser ? 'user' : 'assistant'} ${message.status === 'error' ? 'is-error' : ''}`}>
    <span className="rag-message__avatar" aria-hidden="true">{isUser ? <UserRound size={17} /> : <Bot size={18} />}</span>
    <div className="rag-message__content">
      <header><strong>{isUser ? t('ragAssistant.chat.you') : t('ragAssistant.chat.assistant')}</strong>{message.createdAt && <time dateTime={message.createdAt}>{formatTime(message.createdAt)}</time>}</header>
      {!isUser && offline && <p className="rag-evidence-note" role="note"><FileSearch size={14} aria-hidden="true" />{t(`ragAssistant.chat.${message.answerMode === 'evidence' ? 'evidenceNote' : 'unverifiedNote'}`)}</p>}
      {message.status === 'generating'
        ? <div className="rag-generating" role="status"><i /><i /><i /><span>{t('ragAssistant.chat.generating')}</span></div>
        : <AssistantResponse content={message.content} blocks={message.blocks} summary={message.summary} onOpenRef={openRef} activeRef={activeRef} t={t} />}
      {!isUser && message.calculations?.[0] && <CalculationCard calculation={message.calculations[0]} onOpenRef={openRef} activeRef={activeRef} t={t} />}
      {notes.length > 0 && <ul className="rag-status-notes">{notes.map((key) => <li key={key}><Info size={13} aria-hidden="true" />{t(`ragAssistant.status.${key}`)}</li>)}</ul>}
      {isUser && <MessageAttachments attachments={message.attachments} formatSize={formatSize} t={t} />}
      {!isUser && <AnswerReferences references={references} legacySources={message.sources || []} onOpenRef={openRef} activeRef={activeRef} t={t} />}
      {!isUser && message.followUpQuestions?.length > 0 && onAsk && <div className="rag-follow-ups" role="group" aria-label={t('ragAssistant.chat.followUps')}>
        {message.followUpQuestions.map((question) => <button type="button" key={question} onClick={() => onAsk(question)} dir="auto">{question}</button>)}
      </div>}
      {activeRef !== null && <ReferencePanel reference={referenceByNumber(references, activeRef)} onClose={closeRef} onOpenRef={openRef} activeRef={activeRef} t={t} locale={locale} dir={dir} />}
    </div>
  </article>;
}
