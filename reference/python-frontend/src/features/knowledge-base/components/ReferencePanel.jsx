import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { ExternalLink, X } from 'lucide-react';
import { CalculationTrace } from './CalculationTrace.jsx';

const KIND_KEYS = {
  company_record: 'kindCompanyRecord', company_summary: 'kindCompanySummary', company_document: 'kindCompanyDocument',
  product_guide: 'kindProductGuide', web_page: 'kindWebPage', calculation: 'kindCalculation', user_input: 'kindUserInput',
};
const CREDIBILITY_KEYS = {
  official: 'credibilityOfficial', primary: 'credibilityPrimary', company: 'credibilityCompany',
  secondary: 'credibilitySecondary', user: 'credibilityUser', calculated: 'credibilityCalculated',
};
const USE_KEYS = {
  supports_fact: 'useFact', calculation: 'useCalculation', calculation_input: 'useCalculationInput',
  supports_estimate: 'useEstimate', supports_analysis: 'useAnalysis', supports_recommendation: 'useRecommendation',
  supports_assumption: 'useAssumption', context: 'useContext',
};

function formatDate(value, locale) {
  if (!value) return null;
  const date = new Date(value.length === 10 ? `${value}T00:00:00` : value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(date);
}

// The details behind one numbered reference: what the source is, who
// published it, the exact supporting excerpt, its dates, jurisdiction,
// credibility and limitations, how the answer used it, and a link to the
// original page or to the KEEL screen holding the record.
export function ReferencePanel({ reference, onClose, onOpenRef, activeRef, t, locale, dir }) {
  const headingRef = useRef(null);
  useEffect(() => {
    headingRef.current?.focus();
    const onKey = (event) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [reference?.n, onClose]);
  if (!reference) return null;

  const dates = [
    ['published', reference.publishedAt], ['effective', reference.effectiveAt],
    ['observed', reference.observedAt], ['retrieved', reference.retrievedAt],
  ].filter(([, value]) => value);
  const headingId = `rag-reference-${reference.n}-title`;
  return <aside className="rag-reference-panel" role="dialog" aria-modal="false" aria-labelledby={headingId} dir={dir}>
    <header>
      <span className="rag-reference-panel__number" aria-hidden="true">{reference.n}</span>
      <h3 id={headingId} tabIndex={-1} ref={headingRef}>{reference.title}</h3>
      <button type="button" className="rag-reference-panel__close" onClick={onClose} aria-label={t('ragAssistant.references.close')}><X size={16} aria-hidden="true" /></button>
    </header>
    <div className="rag-reference-panel__badges">
      <span>{t(`ragAssistant.references.${KIND_KEYS[reference.kind] || 'kindCompanyRecord'}`)}</span>
      {reference.credibility && !['calculated', 'user'].includes(reference.credibility) && <span className={`is-${reference.credibility}`}>{t(`ragAssistant.references.${CREDIBILITY_KEYS[reference.credibility] || 'credibilitySecondary'}`)}</span>}
      {reference.usedAs.map((use) => <span key={use} className="is-use">{t(`ragAssistant.references.${USE_KEYS[use] || 'useContext'}`)}</span>)}
    </div>
    <dl className="rag-reference-panel__facts">
      {reference.organisation && <div><dt>{t('ragAssistant.references.organisation')}</dt><dd><bdi>{reference.organisation}</bdi></dd></div>}
      {reference.locator && <div><dt>{t('ragAssistant.references.location')}</dt><dd><bdi>{reference.locator}</bdi></dd></div>}
      {reference.jurisdiction && <div><dt>{t('ragAssistant.references.jurisdiction')}</dt><dd><bdi>{reference.jurisdiction}</bdi></dd></div>}
      {reference.appliesTo && <div><dt>{t('ragAssistant.references.appliesTo')}</dt><dd><bdi>{reference.appliesTo}</bdi></dd></div>}
      {dates.map(([key, value]) => <div key={key}><dt>{t(`ragAssistant.references.date.${key}`)}</dt><dd><time dateTime={value}>{formatDate(value, locale)}</time></dd></div>)}
    </dl>
    {reference.excerpt && <figure className="rag-reference-panel__excerpt">
      <figcaption>{t(reference.kind === 'calculation' ? 'ragAssistant.references.method' : 'ragAssistant.references.excerpt')}</figcaption>
      <blockquote dir="auto">{reference.excerpt}</blockquote>
    </figure>}
    {reference.calculation && <CalculationTrace calculation={reference.calculation} inputRefs={reference.inputRefs} onOpenRef={onOpenRef} activeRef={activeRef} t={t} />}
    {reference.limitations.length > 0 && <div className="rag-reference-panel__limits" role="note">
      <strong>{t('ragAssistant.references.limitations')}</strong>
      <ul>{reference.limitations.map((text) => <li key={text} dir="auto">{text}</li>)}</ul>
    </div>}
    <footer>
      {reference.url && <a href={reference.url} target="_blank" rel="noopener noreferrer"><ExternalLink size={14} aria-hidden="true" />{t('ragAssistant.references.openSource')}<span className="ceopro-visually-hidden"> {t('ragAssistant.references.newTab')}</span></a>}
      {!reference.url && reference.route && <Link to={reference.route}>{t('ragAssistant.references.openRecord')}</Link>}
    </footer>
  </aside>;
}
