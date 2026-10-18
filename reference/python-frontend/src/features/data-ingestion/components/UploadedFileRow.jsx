import { Trash2 } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { getFileTypeAsset } from '../config/fileTypeAssets.js';

const formatSize = (size) => size < 1024 * 1024
  ? `${Math.max(1, Math.round(size / 1024))} KB`
  : `${(size / (1024 * 1024)).toFixed(1)} MB`;

export function UploadedFileRow({ file, onRemove }) {
  const { t } = useI18n();
  const fileType = getFileTypeAsset(file.name);

  return (
    <li className="ceopro-uploaded-file">
      <span className={`ceopro-uploaded-file__icon ${fileType.className}`}><img src={fileType.src} alt={fileType.label} /></span>
      <span className="ceopro-uploaded-file__copy"><strong>{file.name}</strong><small>{formatSize(file.size)}</small></span>
      <span className="ceopro-uploaded-file__status">✓ {t('dataIngestion.ready')}</span>
      <button type="button" onClick={onRemove} aria-label={t('dataIngestion.removeFile', { name: file.name })}><Trash2 size={16} /></button>
    </li>
  );
}
