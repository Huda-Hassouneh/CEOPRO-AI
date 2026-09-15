import { Bot, UserRound } from 'lucide-react';
import { AssistantResponse } from './AssistantResponse.jsx';
import { SourceCitationList } from './SourceCitationList.jsx';
import { MessageAttachments } from './MessageAttachments.jsx';

export function ChatMessage({ message, t, formatTime, formatSize, onOpenSource }) {
  const isUser = message.role === 'user';
  return <article className={`rag-message is-${isUser ? 'user' : 'assistant'} ${message.status === 'error' ? 'is-error' : ''}`}>
    <span className="rag-message__avatar" aria-hidden="true">{isUser ? <UserRound size={17} /> : <Bot size={18} />}</span>
    <div className="rag-message__content">
      <header><strong>{isUser ? t('ragAssistant.chat.you') : t('ragAssistant.chat.assistant')}</strong>{message.createdAt && <time dateTime={message.createdAt}>{formatTime(message.createdAt)}</time>}</header>
      {message.status === 'generating' ? <div className="rag-generating" role="status"><i /><i /><i /><span>{t('ragAssistant.chat.generating')}</span></div> : <AssistantResponse content={message.content} />}
      {isUser && <MessageAttachments attachments={message.attachments} formatSize={formatSize} t={t} />}
      {!isUser && <SourceCitationList sources={message.sources} t={t} onOpenSource={onOpenSource} />}
    </div>
  </article>;
}
