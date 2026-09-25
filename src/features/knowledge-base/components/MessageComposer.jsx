import { useRef, useState } from 'react';
import { Paperclip, SendHorizontal } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import { ACCEPTED_UPLOAD_FILE_TYPES, getInvalidUploadFile, isSupportedUploadImage } from '../../data-ingestion/utils/fileValidation.js';
import { MessageAttachments } from './MessageAttachments.jsx';

const createAttachmentId = () => globalThis.crypto?.randomUUID?.() || `attachment-${Date.now()}-${Math.random()}`;

const readImagePreview = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(reader.result);
  reader.onerror = () => reject(reader.error);
  reader.readAsDataURL(file);
});

export function MessageComposer({ value, onChange, attachments, onAttachmentsChange, onAttachmentError, onSubmit, disabled, formatSize, t, allowAttachments = true }) {
  const textareaRef = useRef(null);
  const inputRef = useRef(null);
  const [readingFiles, setReadingFiles] = useState(false);
  const submit = (event) => {
    event?.preventDefault();
    if ((!value.trim() && attachments.length === 0) || disabled || readingFiles) return;
    onSubmit(value.trim(), attachments);
  };
  const onKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };
  const selectAttachments = async (fileList) => {
    const selectedFiles = Array.from(fileList);
    const invalid = getInvalidUploadFile(selectedFiles);
    if (invalid) {
      onAttachmentError('invalid', invalid.name);
      return;
    }
    setReadingFiles(true);
    try {
      const existing = new Set(attachments.map((attachment) => `${attachment.name}-${attachment.size}-${attachment.lastModified}`));
      const next = [];
      for (const file of selectedFiles) {
        const key = `${file.name}-${file.size}-${file.lastModified}`;
        if (existing.has(key)) continue;
        const image = isSupportedUploadImage(file);
        next.push({ id: createAttachmentId(), name: file.name, size: file.size, type: file.type, lastModified: file.lastModified, kind: image ? 'image' : 'file', previewUrl: image ? await readImagePreview(file) : null, file });
      }
      onAttachmentsChange([...attachments, ...next]);
    } catch {
      onAttachmentError('read');
    } finally {
      setReadingFiles(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  };
  const removeAttachment = (id) => onAttachmentsChange(attachments.filter((attachment) => attachment.id !== id));

  return <form className="rag-composer" onSubmit={submit}>
    <MessageAttachments attachments={attachments} onRemove={removeAttachment} formatSize={formatSize} t={t} compact />
    <div className="rag-composer__input">
      {allowAttachments && <button type="button" className="rag-composer__attach" disabled={disabled || readingFiles} onClick={() => inputRef.current?.click()} aria-label={t('ragAssistant.attachments.add')} title={t('ragAssistant.attachments.add')}><Paperclip size={17} aria-hidden="true" /></button>}
      {allowAttachments && <input ref={inputRef} className="ceopro-visually-hidden" type="file" multiple accept={ACCEPTED_UPLOAD_FILE_TYPES} onChange={(event) => selectAttachments(event.target.files)} />}
      <textarea ref={textareaRef} rows="1" value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} onKeyDown={onKeyDown} placeholder={t('ragAssistant.composer.placeholder')} aria-label={t('ragAssistant.composer.placeholder')} />
      <Button type="submit" size="sm" disabled={(!value.trim() && attachments.length === 0) || disabled || readingFiles} loading={disabled} loadingLabel={t('ragAssistant.chat.generating')} aria-label={t('ragAssistant.composer.send')}><SendHorizontal size={16} aria-hidden="true" /></Button>
    </div>
    <small>{t('ragAssistant.composer.helper')}</small>
  </form>;
}
