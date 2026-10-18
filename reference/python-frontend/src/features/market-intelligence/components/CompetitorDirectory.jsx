import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ExternalLink, Globe, MapPin, Plus, Search, Star, StarOff, Store, UserPlus } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { ApexButton, Meter, Panel, Pill, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import { useDiscoveredCompetitors, useTrackCompetitor } from '../hooks/useDiscovery.js';
import { useCompetitorOverview } from '../hooks/useCompetitorData.js';
import { CompetitorDataChips } from './DataCompleteness.jsx';

const STATUSES = ['tracked', 'suggested', 'all'];
const SORTS = ['relevance', 'distance', 'rating', 'reviews', 'name', 'recent'];
const ORIGINS = ['', 'map', 'web', 'manual'];
const RELATIONSHIPS = ['', 'DIRECT', 'INDIRECT', 'RELATED', 'UNVERIFIED', 'with_prices'];
const RELATIONSHIP_TONE = { DIRECT: 'success', INDIRECT: 'accent', RELATED: 'neutral', UNVERIFIED: 'warning' };

// Why a business is labelled as it is, in words (market_discovery/relevance.py).
function relationshipReason(reasons, t) {
  const why = (reasons || []).find((r) => ['same_products', 'same_specialty', 'same_trade', 'same_industry', 'related_industry',
    'name_matches_industry', 'not_confirmed'].includes(r.code));
  if (!why) return null;
  return t(`discovery.reason.${why.code}`, { count: why.count, term: why.term, where: why.where ? t(`discovery.reason.where.${why.where}`) : '' });
}

// What its own website gave, or why nothing could be read.
function websiteSummary(c, t) {
  const read = c.website_read || {};
  if (!c.website_url) return null;
  if (!read.status) return t('discovery.website.notYet');
  if (read.products > 0) {
    return [t('discovery.website.items', { count: read.products }), t('discovery.website.prices', { count: read.prices }),
      c.matched_prices > 0 ? t('discovery.website.matched', { count: c.matched_prices }) : null].filter(Boolean).join(' · ');
  }
  return t(`intel.status.${read.status}`, { defaultValue: t('intel.status.failed') });
}

function confidenceTone(value) {
  if (value == null) return 'neutral';
  if (value >= 0.75) return 'success';
  if (value >= 0.5) return 'accent';
  return 'warning';
}

// Every competitor the company knows of, tracked or suggested by the market
// scan, with where it was found and - for tracked ones - how its prices compare.
export function CompetitorDirectory({ pricing = {}, planLimit }) {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const [status, setStatus] = useState('tracked');
  const [sort, setSort] = useState('relevance');
  const [origin, setOrigin] = useState('');
  const [relationship, setRelationship] = useState('');
  const [search, setSearch] = useState('');
  const filters = useMemo(() => ({ status, sort, origin, relationship, q: search.trim() }), [status, sort, origin, relationship, search]);
  const query = useDiscoveredCompetitors(filters);
  const track = useTrackCompetitor();
  // Ratings, comments, agreement and data completeness for each tracked competitor (one bulk read; the list works without it).
  const overview = useCompetitorOverview();
  const number = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  const isArabic = locale?.startsWith('ar');
  const competitorPath = (id) => routePaths.marketCompetitorDetail.replace(':competitorId', id);

  const counts = query.data?.counts;
  const atLimit = planLimit != null && counts && counts.tracked >= planLimit;
  const trackError = track.error?.response?.status === 402 || track.error?.response?.status === 403
    ? t('discovery.list.limitReached') : track.isError ? t('discovery.list.trackFailed') : null;

  const controls = (
    <>
      <label className="apex-search"><Search size={15} aria-hidden="true" /><input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t('discovery.list.search')} aria-label={t('discovery.list.search')} /></label>
      <select className="apex-select" value={sort} onChange={(e) => setSort(e.target.value)} aria-label={t('discovery.list.sort')}>
        {SORTS.map((key) => <option key={key} value={key}>{t(`discovery.sort.${key}`)}</option>)}
      </select>
      <select className="apex-select" value={relationship} onChange={(e) => setRelationship(e.target.value)} aria-label={t('discovery.relationship.label')}>
        {RELATIONSHIPS.map((key) => {
          const count = key && key !== 'with_prices' ? counts?.by_relationship?.[key] : null;
          return <option key={key || 'any'} value={key}>{t(`discovery.relationship.filter.${key || 'any'}`)}{count != null ? ` · ${number.format(count)}` : ''}</option>;
        })}
      </select>
      <select className="apex-select" value={origin} onChange={(e) => setOrigin(e.target.value)} aria-label={t('discovery.list.origin')}>
        {ORIGINS.map((key) => <option key={key || 'any'} value={key}>{t(`discovery.origin.${key || 'any'}`)}</option>)}
      </select>
    </>
  );

  return (
    <Panel
      eyebrow={t('discovery.list.eyebrow')}
      title={t('discovery.list.title')}
      subtitle={t('discovery.list.subtitle')}
      actions={(
        <div className="apex-segmented" role="group" aria-label={t('discovery.list.status')}>
          {STATUSES.map((key) => (
            <button key={key} type="button" aria-pressed={status === key} onClick={() => setStatus(key)}>
              {t(`discovery.status.${key}`)}{counts ? ` · ${number.format(counts[key])}` : ''}
            </button>
          ))}
        </div>
      )}
    >
      <div className="competitor-directory__controls">{controls}</div>
      {trackError && <p className="market-scan__note is-error" role="alert">{trackError}</p>}
      {query.isPending ? <StateBlock kind="loading" compact title={t('common.loading')} />
        : query.isError ? <StateBlock kind="error" compact title={t('discovery.error')} onRetry={() => query.refetch()} retryLabel={t('demandApex.actions.retry')} />
          : query.data.competitors.length === 0 ? (
            <StateBlock
              title={t(`discovery.list.empty.${status}`)}
              description={t('discovery.list.emptyHint')}
              action={<ApexButton variant="secondary" icon={Plus} onClick={() => navigate(routePaths.marketAddCompetitor)}>{t('competitorsApex.add.button')}</ApexButton>}
            />
          ) : (
            <ul className="competitor-directory">
              {query.data.competitors.map((c) => {
                const price = pricing[c.competitor_id];
                const name = isArabic && c.name_ar ? c.name_ar : c.name;
                const other = c.name_ar && c.name_ar.trim() !== (c.name || '').trim() ? (isArabic ? c.name : c.name_ar) : null;
                return (
                  <li key={c.competitor_id} className={`competitor-row${c.is_tracked ? ' is-tracked' : ''}`}>
                    <div className="competitor-row__main">
                      <button type="button" className="competitor-row__name" onClick={() => navigate(competitorPath(c.competitor_id))}>
                        {name}{other && <span className="apex-muted" dir="auto"> · {other}</span>}
                      </button>
                      <div className="competitor-row__meta">
                        {c.distance_km != null && <span><MapPin size={12} aria-hidden="true" />{t('discovery.list.km', { km: number.format(c.distance_km) })}</span>}
                        {c.rating != null && <span><Star size={12} aria-hidden="true" />{number.format(c.rating)}{c.review_count ? ` (${number.format(c.review_count)})` : ''}</span>}
                        {c.branch_count > 1 && <span><Store size={12} aria-hidden="true" />{t('discovery.list.branches', { count: c.branch_count })}</span>}
                        {c.address && <span className="competitor-row__address" dir="auto">{c.address}</span>}
                        {c.website_url && <a href={c.website_url} target="_blank" rel="noreferrer noopener" dir="ltr"><Globe size={12} aria-hidden="true" />{c.website_url.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')}</a>}
                      </div>
                      {(c.relationship || websiteSummary(c, t)) && (
                        <div className="competitor-row__evidence">
                          {c.relationship && <Pill tone={RELATIONSHIP_TONE[c.relationship]}>{t(`discovery.relationship.${c.relationship}`)}</Pill>}
                          {c.relationship && relationshipReason(c.reasons, t) && <span className="apex-muted">{relationshipReason(c.reasons, t)}</span>}
                          {websiteSummary(c, t) && <span className="apex-muted competitor-row__website">{websiteSummary(c, t)}</span>}
                        </div>
                      )}
                      {c.is_tracked && <CompetitorDataChips data={overview.data?.[c.competitor_id]} competitorId={c.competitor_id} />}
                      <div className="competitor-row__sources">
                        {c.origin === 'manual' && !c.sources.length && <Pill>{t('discovery.origin.manual')}</Pill>}
                        {c.is_demo && <Pill tone="warning">{t('discovery.list.demo')}</Pill>}
                        {c.sources.filter((s) => s.source !== 'demo').map((s, index) => (
                          s.url
                            ? <a key={`${s.source}-${index}`} className="apex-pill apex-pill--neutral" href={s.url} target="_blank" rel="noreferrer noopener">{t(`discovery.sources.${s.source}`)}<ExternalLink size={10} aria-hidden="true" /></a>
                            : <Pill key={`${s.source}-${index}`}>{t(`discovery.sources.${s.source}`)}</Pill>
                        ))}
                      </div>
                    </div>
                    <div className="competitor-row__scores">
                      {c.relevance != null && (
                        <div className="competitor-row__score">
                          <span>{t('discovery.list.relevance')}</span>
                          <Meter value={Math.round(c.relevance * 100)} max={100} label={t('discovery.list.relevance')} />
                        </div>
                      )}
                      {c.confidence != null && <Pill tone={confidenceTone(c.confidence)}>{t(`discovery.confidence.${c.confidence >= 0.75 ? 'high' : c.confidence >= 0.5 ? 'medium' : 'low'}`)}</Pill>}
                      {price && price.products_priced > 0 && (
                        <span className="apex-muted competitor-row__price">
                          {t('discovery.list.priced', { count: price.products_priced })}
                          {price.average_gap_pct != null && ` · ${price.average_gap_pct > 0 ? '+' : ''}${number.format(price.average_gap_pct)}%`}
                        </span>
                      )}
                    </div>
                    <div className="competitor-row__action">
                      {c.is_tracked
                        ? <ApexButton size="sm" variant="ghost" icon={StarOff} loading={track.isPending && track.variables?.id === c.competitor_id} onClick={() => track.mutate({ id: c.competitor_id, track: false })}>{t('discovery.list.untrack')}</ApexButton>
                        : <ApexButton size="sm" variant="secondary" icon={UserPlus} disabled={atLimit} title={atLimit ? t('discovery.list.limitReached') : undefined} loading={track.isPending && track.variables?.id === c.competitor_id} onClick={() => track.mutate({ id: c.competitor_id, track: true })}>{t('discovery.list.track')}</ApexButton>}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
      {query.data?.competitors?.length && query.hasNextPage ? (
        <div className="competitor-directory__more">
          <span className="apex-muted">{t('discovery.list.showing', { shown: number.format(query.data.competitors.length), total: number.format(query.data.matching) })}</span>
          <ApexButton size="sm" variant="secondary" loading={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>{t('discovery.list.showMore')}</ApexButton>
        </div>
      ) : null}
    </Panel>
  );
}

export default CompetitorDirectory;
