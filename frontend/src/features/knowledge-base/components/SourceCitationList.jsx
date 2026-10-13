import { useState } from 'react';
import { ChevronDown, FileText, Globe } from 'lucide-react';

const getLocation = (source, t) => {
  if (source.mediaType?.startsWith('image/') || source.type === 'image') return '';
  if (source.pageRange) return t('ragAssistant.sources.pages', { value: source.pageRange });
  if (source.page != null) return t('ragAssistant.sources.page', { value: source.page });
  return '';
};

// Business Copilot Phase 2 (B8/B10/B14): a web-fallback citation must be
// visually distinct from the tenant's own ingested documents - it is
// external, AI-selected search content, never the tenant's own KEEL
// data, and B10's citation-correctness requirement is that this
// distinction is never blurred. knowledgeBaseApi.js's mapSources() sets
// sourceType: 'web' specifically for this (previously mislabeled
// 'knowledge-base', which this fixes).
const isWebSource = (source) => source.sourceType === 'web' || source.origin === 'web';

export function SourceCitationList({ sources, t, onOpenSource }) {
  const [expanded, setExpanded] = useState(true);
  if (!Array.isArray(sources) || sources.length === 0) return null;

  return <section className={`rag-sources ${expanded ? 'is-expanded' : ''}`}>
    <button type="button" className="rag-sources__toggle" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>
      <span>{t('ragAssistant.sources.title')} <small>{sources.length}</small></span>
      <ChevronDown size={15} aria-hidden="true" />
    </button>
    {expanded && <ul>{sources.map((source, index) => {
      const isWeb = isWebSource(source);
      const name = source.documentName || source.name || source.uri;
      const location = getLocation(source, t);
      const sourceKind = isWeb
        ? t('ragAssistant.sources.web')
        : source.sourceType === 'chat-attachment' || source.origin === 'attachment'
          ? t('ragAssistant.sources.chatAttachment')
          : source.sourceType === 'knowledge-base' || source.origin === 'knowledge-base'
            ? t('ragAssistant.sources.knowledgeBase')
            : '';
      const content = <>
        {isWeb ? <Globe size={16} aria-hidden="true" /> : <FileText size={16} aria-hidden="true" />}
        <span>{name && <strong>{name}</strong>}{sourceKind && <b className={isWeb ? 'rag-sources__badge--web' : undefined}>{sourceKind}</b>}{location && <small>{location}</small>}{source.excerpt && <em>{source.excerpt}</em>}</span>
      </>;
      return <li key={source.citationId || `${source.documentId || name}-${index}`}>
        {isWeb && source.uri
          ? <a href={source.uri} target="_blank" rel="noopener noreferrer">{content}</a>
          : onOpenSource && source.documentId ? <button type="button" onClick={() => onOpenSource(source)}>{content}</button> : <div>{content}</div>}
      </li>;
    })}</ul>}
  </section>;
}
