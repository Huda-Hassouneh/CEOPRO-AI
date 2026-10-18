import { FileText, Trash2,RefreshCw } from 'lucide-react';
import { DocumentStatusBadge } from './DocumentStatusBadge.jsx';

export function KnowledgeBaseDocumentRow({ document, t, formatDate, formatSize, actions = [], onDelete, deleting = false,onReindex,reindexing=false }) {
  return <li className="rag-document-row">
    <span className="rag-document-row__icon"><FileText size={18} aria-hidden="true" /></span>
    <div className="rag-document-row__copy"><strong title={document.name}>{document.name}</strong><span>{[document.uploadedAt && formatDate(document.uploadedAt), document.size != null && formatSize(document.size)].filter(Boolean).join(' · ')}</span><DocumentStatusBadge status={document.status} t={t} />
      {document.searchState&&<small>{t(`ragAssistant.search.${document.searchState}`)}</small>}
    </div>
    {document.canDelete&&onReindex&&<button type="button" className="rag-document-row__menu" disabled={deleting||reindexing} onClick={()=>onReindex(document)} aria-label={t('ragAssistant.search.reindex',{name:document.name})}><RefreshCw size={17}/></button>}
    {document.canDelete && onDelete && <button type="button" className="rag-document-row__menu" disabled={deleting}
      onClick={() => onDelete(document)} aria-label={t('ragAssistant.documents.delete', {name:document.name})}><Trash2 size={17} /></button>}
  </li>;
}
