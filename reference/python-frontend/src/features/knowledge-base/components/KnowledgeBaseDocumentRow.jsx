import { FileText, RotateCw } from 'lucide-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { DocumentStatusBadge } from './DocumentStatusBadge.jsx';
import { knowledgeBaseApi } from '../api/knowledgeBaseApi.js';

// A failed document (e.g. uploaded while search indexing was unavailable)
// can be processed again with Retry.
export function KnowledgeBaseDocumentRow({ document, t, formatDate, formatSize }) {
  const queryClient = useQueryClient();
  const retry = useMutation({
    mutationFn: () => knowledgeBaseApi.retryDocument(document.id),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['knowledge-documents'] }),
  });
  return <li className="rag-document-row">
    <span className="rag-document-row__icon"><FileText size={18} aria-hidden="true" /></span>
    <div className="rag-document-row__copy">
      <strong title={document.name}>{document.name}</strong>
      <span>{[document.uploadedAt && formatDate(document.uploadedAt), document.size != null && formatSize(document.size)].filter(Boolean).join(' · ')}</span>
      <DocumentStatusBadge status={retry.isPending ? 'processing' : document.status} t={t} />
      {retry.isError && <small className="apex-field-error">{t('ragAssistant.documents.retryFailed')}</small>}
    </div>
    {document.status === 'failed' && (
      <button type="button" className="rag-document-row__menu" onClick={() => retry.mutate()} disabled={retry.isPending} aria-label={t('ragAssistant.documents.retry', { name: document.name })} title={t('ragAssistant.documents.retry', { name: document.name })}>
        <RotateCw size={16} className={retry.isPending ? 'apex-rotating' : ''} />
      </button>
    )}
  </li>;
}
