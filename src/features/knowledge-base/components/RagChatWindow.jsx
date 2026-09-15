import { Bot, Library, RotateCcw } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import { ChatMessage } from './ChatMessage.jsx';
import { MessageComposer } from './MessageComposer.jsx';

export function RagChatWindow({ messages, question, onQuestionChange, attachments, onAttachmentsChange, onAttachmentError, onSubmit, pending, t, formatTime, formatSize, knowledgeOpen, onOpenKnowledge }) {
  return <section className="rag-chat-panel" aria-label={t('ragAssistant.chat.regionLabel')}>
    <div className="rag-chat-panel__toolbar"><div><span className="rag-chat-panel__mark"><Bot size={18} /></span><strong>{t('ragAssistant.chat.assistant')}</strong></div>{!knowledgeOpen && <Button size="sm" variant="outline" leadingIcon={<Library size={15} />} onClick={onOpenKnowledge}>{t('ragAssistant.knowledge.open')}</Button>}</div>
    <div className="rag-conversation" aria-live="polite">
      {messages.length === 0 ? <div className="rag-empty-conversation"><span><Bot size={28} /></span><h2>{t('ragAssistant.empty.title')}</h2><p>{t('ragAssistant.empty.description')}</p><div>{['summary', 'pricing', 'compare'].map((key) => <button type="button" key={key} onClick={() => onQuestionChange(t(`ragAssistant.empty.prompts.${key}`))}>{t(`ragAssistant.empty.prompts.${key}`)}</button>)}</div></div> : messages.map((message) => <ChatMessage key={message.messageId} message={message} t={t} formatTime={formatTime} formatSize={formatSize} />)}
      {pending && <ChatMessage message={{ messageId: 'generating', role: 'assistant', status: 'generating' }} t={t} formatTime={formatTime} formatSize={formatSize} />}
    </div>
    <MessageComposer value={question} onChange={onQuestionChange} attachments={attachments} onAttachmentsChange={onAttachmentsChange} onAttachmentError={onAttachmentError} onSubmit={onSubmit} disabled={pending} formatSize={formatSize} t={t} />
  </section>;
}
