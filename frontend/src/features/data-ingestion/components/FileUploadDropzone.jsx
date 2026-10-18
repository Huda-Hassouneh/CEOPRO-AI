import { RAG_ACCEPTED_FILE_TYPES, getInvalidRagUploadFile } from "../../knowledge-base/utils/ragUploadContract.js";
import { useRef, useState } from 'react';
import { CloudUpload } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { UploadedFileRow } from './UploadedFileRow.jsx';
import {
  BUSINESS_UPLOAD_FILE_TYPES,
  STRUCTURED_BUSINESS_UPLOAD_FILE_TYPES,
  getInvalidBusinessUploadFile,
  getInvalidStructuredBusinessUploadFile
} from '../utils/fileValidation.js';

export function FileUploadDropzone({ files, onFilesChange, kind = 'sales', disabled = false }) {
  const { t } = useI18n();
  const inputRef = useRef(null);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState('');

  const addFiles = (incoming) => {
    if (disabled) return;
    const nextFiles = Array.from(incoming);
    if (!['sales', 'rag'].includes(kind) && nextFiles.length !== 1) {
      setError(t('connectData.review.oneFile'));
      return;
    }
    const invalid = kind === 'rag' ? getInvalidRagUploadFile(nextFiles) : kind === 'sales'
      ? getInvalidBusinessUploadFile(nextFiles)
      : getInvalidStructuredBusinessUploadFile(nextFiles);
    if (invalid) {
      setError(t(kind === 'rag' ? 'ragAssistant.upload.invalidFile' : 'dataIngestion.invalidFile', { name: invalid.name }));
      return;
    }
    setError('');
    const existing = new Set(files.map((file) => `${file.name}-${file.size}`));
    onFilesChange(['sales','rag'].includes(kind)
      ? [...files, ...nextFiles.filter((file) => !existing.has(`${file.name}-${file.size}`))]
      : nextFiles);
  };

  return (
    <div>
      <div
        className={`ceopro-file-dropzone ${dragActive ? 'is-dragging' : ''}`}
        onDragEnter={(event) => { event.preventDefault(); setDragActive(true); }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setDragActive(false); }}
        onDrop={(event) => { event.preventDefault(); setDragActive(false); addFiles(event.dataTransfer.files); }}
      >
        <CloudUpload size={39} aria-hidden="true" />
        <strong>{t('dataIngestion.dropTitle')}</strong>
        <span>{t('dataIngestion.or')}</span>
        <Button size="sm" disabled={disabled} onClick={() => inputRef.current?.click()}>{t('dataIngestion.browse')}</Button>
        <input
          ref={inputRef}
          className="ceopro-visually-hidden"
          type="file"
          multiple={['sales','rag'].includes(kind)}
          disabled={disabled}
          accept={kind === 'rag' ? RAG_ACCEPTED_FILE_TYPES : kind === 'sales' ? BUSINESS_UPLOAD_FILE_TYPES : STRUCTURED_BUSINESS_UPLOAD_FILE_TYPES}
          onChange={(event) => { addFiles(event.target.files); event.target.value = ''; }}
        />
        <small>{kind === 'rag' ? t('ragAssistant.upload.supported') : kind === 'sales' ? t('dataIngestion.supported') : t('connectData.upload.structuredFormats')}</small>
        <small>{t(kind === 'rag' ? 'ragAssistant.upload.maxSize' : 'dataIngestion.maxSize')}</small>
      </div>
      {error && <p className="ceopro-upload-error" role="alert">{error}</p>}
      {files.length > 0 && (
        <section className="ceopro-upload-list" aria-live="polite">
          <header><h2>{t('dataIngestion.uploadedFiles', { count: files.length })}</h2><button type="button" onClick={() => onFilesChange([])}>{t('dataIngestion.removeAll')}</button></header>
          <ul>{files.map((file) => <UploadedFileRow key={`${file.name}-${file.size}`} file={file} onRemove={() => onFilesChange(files.filter((item) => item !== file))} />)}</ul>
        </section>
      )}
    </div>
  );
}
