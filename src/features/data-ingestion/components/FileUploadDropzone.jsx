import { useRef, useState } from 'react';
import { CloudUpload } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { UploadedFileRow } from './UploadedFileRow.jsx';
import { ACCEPTED_UPLOAD_FILE_TYPES, getInvalidUploadFile } from '../utils/fileValidation.js';

export function FileUploadDropzone({ files, onFilesChange }) {
  const { t } = useI18n();
  const inputRef = useRef(null);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState('');

  const addFiles = (incoming) => {
    const nextFiles = Array.from(incoming);
    const invalid = getInvalidUploadFile(nextFiles);
    if (invalid) {
      setError(t('dataIngestion.invalidFile', { name: invalid.name }));
      return;
    }
    setError('');
    const existing = new Set(files.map((file) => `${file.name}-${file.size}`));
    onFilesChange([...files, ...nextFiles.filter((file) => !existing.has(`${file.name}-${file.size}`))]);
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
        <Button size="sm" onClick={() => inputRef.current?.click()}>{t('dataIngestion.browse')}</Button>
        <input
          ref={inputRef}
          className="ceopro-visually-hidden"
          type="file"
          multiple
          accept={ACCEPTED_UPLOAD_FILE_TYPES}
          onChange={(event) => { addFiles(event.target.files); event.target.value = ''; }}
        />
        <small>{t('dataIngestion.supported')}</small>
        <small>{t('dataIngestion.maxSize')}</small>
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
