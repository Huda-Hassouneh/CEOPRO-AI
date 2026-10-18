import { useRef } from 'react';
import { SendHorizontal } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';

// Real bug found live in first-customer E2E acceptance testing: this
// composer used to let a user attach a file via a paperclip button, show
// it in their sent message bubble, and silently drop it - knowledgeBaseApi
// .chat() (api/knowledgeBaseApi.js) only ever sends {question, sessionId}
// to POST /rag/query, which has no file/attachment parameter at all. A
// customer attaching a document and asking "what does this say?" got an
// answer the model never saw the file for, with nothing telling them it
// wasn't used - exactly the kind of advertised-but-non-functional feature
// this acceptance pass is meant to catch. There is no real backend support
// for message attachments to wire this up to (confirmed: knowledgeBaseApi's
// own `capabilities.messageAttachments` already says `false`), so the
// honest fix is to remove the affordance rather than leave it dangling.
export function MessageComposer({ value, onChange, onSubmit, disabled, t }) {
  const textareaRef = useRef(null);
  const submit = (event) => {
    event?.preventDefault();
    if (!value.trim() || disabled) return;
    onSubmit(value.trim());
  };
  const onKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  return <form className="rag-composer" onSubmit={submit}>
    <div className="rag-composer__input">
      <textarea ref={textareaRef} rows="1" value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} onKeyDown={onKeyDown} placeholder={t('ragAssistant.composer.placeholder')} aria-label={t('ragAssistant.composer.placeholder')} />
      <Button type="submit" size="sm" disabled={!value.trim() || disabled} loading={disabled} loadingLabel={t('ragAssistant.chat.generating')} aria-label={t('ragAssistant.composer.send')}><SendHorizontal size={16} aria-hidden="true" /></Button>
    </div>
    <small>{t('ragAssistant.composer.helper')}</small>
  </form>;
}
