import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, BadgeCheck, Check, Megaphone, Newspaper, Pencil, RefreshCw, RotateCcw, Sparkles, Tag, X } from 'lucide-react';
import { useAuth } from '../../../app/providers/AuthProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { ApexButton, Panel, Pill, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import { canReviewPrices, intelChannel, intelOrigin, needsCheck, parseCorrectedPrice } from '../api/competitorDataApi.js';
import { discoveryApi } from '../api/discoveryApi.js';
import { useReviewIntel } from '../hooks/useCompetitorData.js';
import { analysisErrorKey, Citations, SourceLink } from './Citations.jsx';

const CONFIDENCE = (value) => (value >= 0.85 ? 'high' : value >= 0.6 ? 'medium' : 'low');
const ANALYSIS_LISTS = ['strengths', 'weaknesses', 'differentiators', 'opportunities'];

function AnalysisError({ error, t }) {
  const key = analysisErrorKey(error);
  return (
    <p className="market-scan__note is-error" role="alert">
      {t(`intel.analysisErrors.${key}`)}
      {key === 'planLimit' && <> <Link to={routePaths.billing}>{t('marketingApex.errors.openBilling')}</Link></>}
    </p>
  );
}

// The owner's check of one price that was read (not published as structured data): confirm it, correct it, reject
// it, or take the decision back. Owner/admin only; the server enforces it, the UI only offers it.
function PriceReview({ fact, competitorId, t }) {
  const review = useReviewIntel(competitorId);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [problem, setProblem] = useState(null);
  const decide = (verdict, extra = {}) => {
    setProblem(null);
    review.mutate({ intelId: fact.intel_id, verdict, currency: fact.currency, ...extra }, {
      onSuccess: () => setEditing(false),
      onError: (error) => setProblem(error?.response?.status === 403 ? 'forbidden' : 'failed'),
    });
  };
  const save = (event) => {
    event.preventDefault();
    const value = parseCorrectedPrice(draft);
    if (value == null) { setProblem('invalid'); return; }
    decide('CORRECTED', { correctedPrice: value });
  };
  if (fact.verified) {
    return (
      <div className="price-review">
        <Pill tone="success"><BadgeCheck size={12} aria-hidden="true" /> {t(fact.verdict === 'CORRECTED' ? 'intel.review.corrected' : 'intel.review.verified')}</Pill>
        <ApexButton size="sm" variant="ghost" icon={RotateCcw} loading={review.isPending} onClick={() => decide('CLEARED')}>{t('intel.review.undo')}</ApexButton>
        {problem && <span className="market-scan__note is-error" role="alert">{t(`intel.review.${problem}`)}</span>}
      </div>
    );
  }
  if (editing) {
    return (
      <form className="price-review price-review--edit" onSubmit={save}>
        <label className="sr-only" htmlFor={`correct-${fact.intel_id}`}>{t('intel.review.correctedPrice')}</label>
        <input
          id={`correct-${fact.intel_id}`} className="price-review__input" inputMode="decimal" dir="ltr" autoFocus
          value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={String(fact.price ?? '')}
        />
        <ApexButton size="sm" type="submit" icon={Check} loading={review.isPending}>{t('intel.review.save')}</ApexButton>
        <ApexButton size="sm" variant="ghost" onClick={() => { setEditing(false); setProblem(null); }}>{t('intel.review.cancel')}</ApexButton>
        {problem && <span className="market-scan__note is-error" role="alert">{t(`intel.review.${problem}`)}</span>}
      </form>
    );
  }
  return (
    <div className="price-review">
      <ApexButton size="sm" variant="ghost" icon={Check} loading={review.isPending} onClick={() => decide('CONFIRMED')} title={t('intel.review.confirmHint')}>{t('intel.review.confirm')}</ApexButton>
      <ApexButton size="sm" variant="ghost" icon={Pencil} onClick={() => { setDraft(String(fact.price ?? '')); setEditing(true); }}>{t('intel.review.correct')}</ApexButton>
      <ApexButton size="sm" variant="ghost" icon={X} loading={review.isPending} onClick={() => decide('REJECTED')} title={t('intel.review.rejectHint')}>{t('intel.review.reject')}</ApexButton>
      {problem && <span className="market-scan__note is-error" role="alert">{t(`intel.review.${problem}`)}</span>}
    </div>
  );
}

// Where a news item came from, when known (older rows have none).
const NEWS_ORIGIN = { own_site: 'intel.newsFromSite', web_search: 'intel.newsFromSearch' };

// What a competitor publishes on its own website (each fact linked to its
// page and dated), news naming it, and a clearly labelled AI analysis of
// those facts in which every point cites them.
export function CompetitorIntel({ competitor, t, locale }) {
  const queryClient = useQueryClient();
  const { roles } = useAuth();
  const canReview = canReviewPrices(roles);
  const id = competitor.competitor_id;
  const intel = competitor.intel || { products: [], promotions: [], messages: [], social: [], analysis: null };
  const date = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }), [locale]);
  const when = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }), [locale]);
  const money = (value, currency) => {
    if (!currency) return new Intl.NumberFormat(locale, { maximumFractionDigits: 3 }).format(value);
    try { return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(value); } catch { return `${value} ${currency}`; }
  };
  const news = useQuery({ queryKey: ['discovery-news', id], queryFn: () => discoveryApi.news({ competitorId: id, limit: 10 }) });
  const refreshAll = () => queryClient.invalidateQueries({ queryKey: ['discovery-competitor', id] });
  const refresh = useMutation({ mutationFn: () => discoveryApi.refresh(id), onSuccess: refreshAll });
  const analyse = useMutation({ mutationFn: () => discoveryApi.analyse(id), onSuccess: refreshAll });
  const analysis = analyse.data && !analyse.data.insufficient_evidence ? analyse.data : intel.analysis;
  const thin = analyse.data?.insufficient_evidence;
  const conflicts = new Set(intel.price_conflicts || []);
  const nothingRead = !intel.products.length && !intel.promotions.length && !intel.messages.length;
  const statusNote = intel.status && !['ok', 'prices_found'].includes(intel.status) ? t(`intel.status.${intel.status}`, { defaultValue: t('intel.status.failed') }) : null;

  return (
    <>
      <Panel
        eyebrow={t('intel.eyebrow')}
        title={t('intel.title')}
        subtitle={intel.checked_at ? t('intel.checkedAt', { date: when.format(new Date(intel.checked_at)) }) : t('intel.neverChecked')}
        actions={competitor.website_url && (
          <ApexButton variant="ghost" size="sm" icon={RefreshCw} loading={refresh.isPending} onClick={() => refresh.mutate()}>
            {intel.checked_at ? t('intel.refresh') : t('intel.read')}
          </ApexButton>
        )}
      >
        {refresh.isError && <p className="market-scan__note is-error" role="alert">{t('intel.refreshFailed')}</p>}
        {statusNote && <p className="market-scan__note is-warning">{statusNote}</p>}
        {!competitor.website_url ? <StateBlock compact title={t('intel.noWebsite')} description={t('intel.noWebsiteHint')} /> : nothingRead ? (
          <StateBlock compact title={t('intel.nothingYet')} description={t('intel.nothingYetHint')} />
        ) : (
          <div className="intel-sections">
            {intel.products.length > 0 && (
              <section>
                <h3><Tag size={14} aria-hidden="true" /> {t('intel.products')}</h3>
                {conflicts.size > 0 && <p className="market-scan__note is-warning"><AlertTriangle size={13} aria-hidden="true" /> {t('intel.conflicts')}</p>}
                <div className="apex-table-wrap"><table className="apex-table intel-prices">
                  <thead><tr><th>{t('intel.product')}</th><th className="apex-table__num">{t('intel.price')}</th><th>{t('intel.confidence')}</th><th>{t('intel.source')}</th>{canReview && <th>{t('intel.review.column')}</th>}</tr></thead>
                  <tbody>{intel.products.slice(0, 30).map((p, index) => (
                    <tr key={p.intel_id || `${p.name}-${p.price}-${index}`} className={conflicts.has(p.name.toLowerCase()) ? 'is-conflict' : ''}>
                      <td dir="auto">
                        {p.name}
                        <div className="price-origin">
                          {intelChannel(p) && <Pill tone="neutral">{t(`intel.channel.${p.channel}`, { defaultValue: p.channel })}</Pill>}
                          {intelOrigin(p) !== 'page' && <span className="apex-muted">{t(`intel.origin.${intelOrigin(p)}`)}</span>}
                          {p.also_seen_in?.length > 0 && <span className="apex-muted">{t('intel.alsoSeen', { count: p.also_seen_in.length })}</span>}
                          {needsCheck(p) && <span className="price-origin__check">{t('intel.review.checkThis')}</span>}
                        </div>
                      </td>
                      <td className="apex-table__num">
                        {p.price != null ? money(p.price, p.currency) : '—'}
                        {p.read_price != null && p.read_price !== p.price && <div className="apex-muted price-origin__was">{t('intel.review.wasRead', { price: money(p.read_price, p.currency) })}</div>}
                        {!p.verified && p.conflicts_with_price != null && p.conflicts_with_price !== p.price && <div className="apex-muted price-origin__was">{t('intel.review.conflictsWith', { price: money(p.conflicts_with_price, p.currency) })}</div>}
                      </td>
                      <td>{p.verified
                        ? <Pill tone="success">{t('intel.review.checkedByYou')}</Pill>
                        : <Pill tone={CONFIDENCE(p.confidence) === 'high' ? 'success' : 'neutral'}>{t(`intel.confidenceLevels.${CONFIDENCE(p.confidence)}`)}</Pill>}</td>
                      <td><SourceLink url={p.source_url} t={t} /> <span className="apex-muted">{date.format(new Date(p.retrieved_at))}</span></td>
                      {canReview && <td>{p.intel_id && p.price != null ? <PriceReview fact={p} competitorId={id} t={t} /> : null}</td>}
                    </tr>
                  ))}</tbody>
                </table></div>
              </section>
            )}
            {intel.promotions.length > 0 && (
              <section>
                <h3><Megaphone size={14} aria-hidden="true" /> {t('intel.promotions')}</h3>
                <ul className="intel-list">{intel.promotions.map((p) => <li key={p.intel_id || p.text}><span dir="auto">“{p.text}”</span> <SourceLink url={p.source_url} t={t} /></li>)}</ul>
              </section>
            )}
            {intel.messages.length > 0 && (
              <section>
                <h3>{t('intel.messages')}</h3>
                <ul className="intel-list">{intel.messages.slice(0, 6).map((m) => <li key={m.text}><span dir="auto">“{m.text}”</span> <SourceLink url={m.source_url} t={t} /></li>)}</ul>
              </section>
            )}
          </div>
        )}
        <p className="apex-source">{t('intel.provenance')}</p>
      </Panel>

      <Panel
        eyebrow={t('intel.analysisEyebrow')}
        title={t('intel.analysisTitle')}
        subtitle={analysis?.generated_at ? t('intel.analysisAt', { date: when.format(new Date(analysis.generated_at)) }) : t('intel.analysisHint')}
        actions={<ApexButton size="sm" icon={Sparkles} loading={analyse.isPending} onClick={() => analyse.mutate()}>{analysis ? t('intel.reanalyse') : t('intel.analyse')}</ApexButton>}
      >
        <p className="intel-ai-label"><Sparkles size={12} aria-hidden="true" /> {t('intel.aiLabel')}</p>
        {analyse.isError && <AnalysisError error={analyse.error} t={t} />}
        {thin && <p className="market-scan__note is-warning">{t('intel.insufficient')}</p>}
        {analysis?.language && !analyse.isPending && analysis.language !== (locale?.startsWith('ar') ? 'ar' : 'en') && (
          <p className="market-scan__note">{t('intel.otherLanguage')}</p>
        )}
        {analysis ? (
          <div className="intel-analysis">
            {['positioning', 'target_audience'].map((key) => analysis[key] && (
              <div key={key}><h3>{t(`intel.analysis.${key}`)}</h3><p dir="auto">{analysis[key].text} <Citations citations={analysis[key].citations} t={t} /></p></div>
            ))}
            {ANALYSIS_LISTS.map((key) => analysis[key]?.length > 0 && (
              <div key={key}><h3>{t(`intel.analysis.${key}`)}</h3>
                <ul>{analysis[key].map((point) => <li key={point.text} dir="auto">{point.text} <Citations citations={point.citations} t={t} /></li>)}</ul>
              </div>
            ))}
          </div>
        ) : !thin && <StateBlock compact title={t('intel.noAnalysis')} description={t('intel.noAnalysisHint')} />}
      </Panel>

      {news.data?.length > 0 && (
        <Panel eyebrow={t('intel.newsEyebrow')} title={t('intel.competitorNews')}>
          <ul className="intel-news">
            {news.data.map((a) => (
              <li key={a.url}><Newspaper size={14} aria-hidden="true" />
                <div><a href={a.url} target="_blank" rel="noreferrer noopener" dir="auto">{a.title}</a>
                  {a.summary && <p className="intel-news__summary" dir="auto">{a.summary}</p>}
                  <div className="apex-muted">{[a.source_domain, a.published_at && date.format(new Date(a.published_at)), NEWS_ORIGIN[a.source_kind] && t(NEWS_ORIGIN[a.source_kind])].filter(Boolean).join(' · ')}</div></div>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </>
  );
}

export default CompetitorIntel;
