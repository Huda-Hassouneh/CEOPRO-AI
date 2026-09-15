import { FileText, MoreVertical } from 'lucide-react';
import { DocumentStatusBadge } from './DocumentStatusBadge.jsx';

export function KnowledgeBaseDocumentRow({ document, t, formatDate, formatSize, actions = [] }) {
  return <li className="rag-document-row">
    <span className="rag-document-row__icon"><FileText size={18} aria-hidden="true" /></span>
    <div className="rag-document-row__copy"><strong title={document.name}>{document.name}</strong><span>{[document.uploadedAt && formatDate(document.uploadedAt), document.size != null && formatSize(document.size)].filter(Boolean).join(' · ')}</span><DocumentStatusBadge status={document.status} t={t} /></div>
    {actions.length > 0 && <button type="button" className="rag-document-row__menu" aria-label={t('ragAssistant.documents.actions', { name: document.name })}><MoreVertical size={17} /></button>}
  </li>;
}
