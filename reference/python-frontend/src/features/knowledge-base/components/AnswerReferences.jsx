import { useState } from 'react';
import { ChevronDown, FileText, Globe, Calculator, Database } from 'lucide-react';

const ICONS = { web_page: Globe, calculation: Calculator, company_document: FileText, company_summary: FileText };

// The numbered reference list under an answer, matching the markers in the
// text; choosing one opens it in the reference panel. Answers saved before
// claim-level references existed show their original source list.
export function AnswerReferences({ references, legacySources, onOpenRef, activeRef, t }) {
  const [expanded, setExpanded] = useState(false);
  const count = references.length || legacySources.length;
  if (!count) return null;
  return <section className={`rag-sources ${expanded ? 'is-expanded' : ''}`} aria-label={t('ragAssistant.references.title')}>
    <button type="button" className="rag-sources__toggle" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>
      <span>{t('ragAssistant.references.title')} <small>{count}</small></span>
      <ChevronDown size={15} aria-hidden="true" />
    </button>
    {expanded && references.length > 0 && <ol className="rag-sources__list">{references.map((reference) => {
      const Icon = ICONS[reference.kind] || Database;
      return <li key={reference.n}>
        <button type="button" onClick={(event) => onOpenRef(reference.n, event.currentTarget)} aria-haspopup="dialog" aria-expanded={activeRef === reference.n}>
          <span className="rag-sources__number" aria-hidden="true">{reference.n}</span>
          <Icon size={15} aria-hidden="true" />
          <span><strong dir="auto">{reference.title}</strong>{reference.organisation && <small dir="auto">{reference.organisation}</small>}</span>
        </button>
      </li>;
    })}</ol>}
    {expanded && !references.length && <ul>{legacySources.map((source) => <li key={source.citationId}>
      {source.uri
        ? <a href={source.uri} target="_blank" rel="noopener noreferrer"><Globe size={16} aria-hidden="true" /><span><strong>{source.name}</strong><b className="rag-sources__badge--web">{t('ragAssistant.sources.web')}</b></span></a>
        : <div><FileText size={16} aria-hidden="true" /><span><strong>{source.name}</strong><b>{t('ragAssistant.sources.knowledgeBase')}</b></span></div>}
    </li>)}</ul>}
  </section>;
}
