import { useState } from 'react';
import { ChevronDown, FileText } from 'lucide-react';

const getLocation = (source, t) => {
  if (source.mediaType?.startsWith('image/') || source.type === 'image') return '';
  if (source.pageRange) return t('ragAssistant.sources.pages', { value: source.pageRange });
  if (source.page != null) return t('ragAssistant.sources.page', { value: source.page });
  return '';
};

export function SourceCitationList({ sources, t, onOpenSource }) {
  const [expanded, setExpanded] = useState(true);
  if (!Array.isArray(sources) || sources.length === 0) return null;

  return <section className={`rag-sources ${expanded ? 'is-expanded' : ''}`}>
    <button type="button" className="rag-sources__toggle" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>
      <span>{t('ragAssistant.sources.title')} <small>{sources.length}</small></span>
      <ChevronDown size={15} aria-hidden="true" />
    </button>
    {expanded && <ul>{sources.map((source, index) => {
      const name = source.documentName || source.name || source.uri;
      const location = getLocation(source, t);
      const sourceKind = source.sourceType === 'chat-attachment' || source.origin === 'attachment'
        ? t('ragAssistant.sources.chatAttachment')
        : source.sourceType === 'knowledge-base' || source.origin === 'knowledge-base'
          ? t('ragAssistant.sources.knowledgeBase')
          : '';
      const content = <><FileText size={16} aria-hidden="true" /><span>{name && <strong>{name}</strong>}{sourceKind && <b>{sourceKind}</b>}{location && <small>{location}</small>}{source.excerpt && <em>{source.excerpt}</em>}</span></>;
      return <li key={source.citationId || `${source.documentId || name}-${index}`}>
        {onOpenSource && source.documentId ? <button type="button" onClick={() => onOpenSource(source)}>{content}</button> : <div>{content}</div>}
      </li>;
    })}</ul>}
  </section>;
}
