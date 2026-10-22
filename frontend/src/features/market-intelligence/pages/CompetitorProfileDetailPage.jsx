import { useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, ExternalLink, Globe, MapPin, Phone, Star, StarOff, Store, UserPlus } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { DashboardLayout } from '../../../app/layouts/DashboardLayout.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import BusinessPageContainer from '../../../shared/components/layout/BusinessPageContainer.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import { ApexButton, Meter, Panel, Pill, Stat, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import { discoveryApi } from '../api/discoveryApi.js';
import { competitorTraits } from '../api/competitorsApi.js';
import { useCompetitorProfile } from '../hooks/useCompetitorProfile.js';
import { useTrackCompetitor } from '../hooks/useDiscovery.js';
import { RecordCompetitorPrice } from '../components/RecordCompetitorPrice.jsx';
import { CompetitorIntel } from '../components/CompetitorIntel.jsx';
import { DataCompleteness } from '../components/DataCompleteness.jsx';
import { CompetitorComments } from '../components/CompetitorComments.jsx';
import { useCompetitorDataStatus } from '../hooks/useCompetitorData.js';
import '../styles/MarketIntelligence.css';
import { safeHref } from '../../../shared/lib/safeUrl.js';

function reasonText(t, number, reason) {
  switch (reason.code) {
    case 'distance': return t('discovery.reasons.distance', { km: number.format(reason.km) });
    case 'branches': return t('discovery.reasons.branches', { count: reason.count });
    case 'reviews': return t('discovery.reasons.reviews', { rating: reason.rating == null ? '—' : number.format(reason.rating), count: number.format(reason.count) });
    case 'sources': return t('discovery.reasons.sources', { count: reason.count });
    default: return t(`discovery.reasons.${reason.code}`);
  }
}

// One competitor: who they are and where that information comes from, why
// it was matched, and - once tracked - how its prices compare with yours.
// "instagram.com/olive.jo" -> "Instagram"; the full address is in the link.
const PROFILE_SITES = { 'instagram.com': 'Instagram', 'facebook.com': 'Facebook', 'tiktok.com': 'TikTok', 'x.com': 'X', 'twitter.com': 'X', 'linkedin.com': 'LinkedIn', 'youtube.com': 'YouTube' };
function profileLabel(link) {
  try {
    const host = new URL(link).hostname.replace(/^www\./, '').replace(/^m\./, '');
    return PROFILE_SITES[host] || host;
  } catch {
    return link;
  }
}

export function CompetitorProfileDetailPage() {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const { competitorId } = useParams();
  const query = useQuery({ queryKey: ['discovery-competitor', competitorId], queryFn: () => discoveryApi.competitor(competitorId), enabled: Boolean(competitorId) });
  const tracked = query.data?.is_tracked;
  const profile = useCompetitorProfile(tracked ? competitorId : null);
  const track = useTrackCompetitor();
  const dataStatus = useCompetitorDataStatus(competitorId, Boolean(tracked));
  const number = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }), [locale]);
  const date = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }), [locale]);
  const money = (value, currency) => { try { return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(value); } catch { return `${value} ${currency}`; } };
  const back = <ApexButton variant="ghost" icon={ArrowLeft} onClick={() => navigate(routePaths.market)}>{t('market.detail.back')}</ApexButton>;

  if (query.isPending) return <DashboardLayout><BusinessPageContainer><Panel><StateBlock kind="loading" title={t('common.loading')} /></Panel></BusinessPageContainer></DashboardLayout>;
  if (query.isError) return <DashboardLayout><BusinessPageContainer><Panel><StateBlock kind="error" title={t('market.empty.detailErrorTitle')} description={t('market.empty.detailErrorDescription')} onRetry={() => query.refetch()} retryLabel={t('demandApex.actions.retry')} /></Panel></BusinessPageContainer></DashboardLayout>;
  const c = query.data;
  if (!c) return <DashboardLayout><BusinessPageContainer><Panel><StateBlock title={t('market.empty.detailNotFoundTitle')} description={t('market.empty.detailNotFoundDescription')} action={back} /></Panel></BusinessPageContainer></DashboardLayout>;

  const isArabic = locale?.startsWith('ar');
  const detail = profile.data?.competitor;
  const comparisons = detail?.price_comparisons || [];
  const strengths = detail ? competitorTraits(t, detail.strength_codes, detail.strengths) : [];
  const weaknesses = detail ? competitorTraits(t, detail.weakness_codes, detail.weaknesses) : [];
  const toggle = () => track.mutate({ id: c.competitor_id, track: !c.is_tracked }, { onSuccess: () => query.refetch() });

  return (
    <DashboardLayout>
      <BusinessPageContainer>
        <PageHeader
          title={isArabic && c.name_ar ? c.name_ar : c.name}
          subtitle={[c.industry, c.city].filter(Boolean).join(' · ') || t('discovery.detail.subtitle')}
          actions={(
            <>
              {back}
              <ApexButton variant={c.is_tracked ? 'ghost' : 'primary'} icon={c.is_tracked ? StarOff : UserPlus} loading={track.isPending} onClick={toggle}>
                {c.is_tracked ? t('discovery.list.untrack') : t('discovery.list.track')}
              </ApexButton>
            </>
          )}
        />
        {track.isError && <p className="market-scan__note is-error" role="alert">{track.error?.response?.status === 402 ? t('discovery.list.limitReached') : t('discovery.list.trackFailed')}</p>}
        <div className="apex-page">
          <div className="apex-grid apex-grid--stats">
            <Stat label={t('discovery.detail.distance')} value={c.distance_km != null ? t('discovery.list.km', { km: number.format(c.distance_km) }) : '—'} icon={MapPin} />
            <Stat label={t('discovery.detail.rating')} value={c.rating != null ? `${number.format(c.rating)} / 5` : '—'} hint={c.review_count ? t('discovery.detail.reviews', { count: number.format(c.review_count) }) : t('discovery.detail.noReviews')} icon={Star} tone="warning" />
            <Stat label={t('discovery.detail.branches')} value={number.format(Math.max(c.branch_count || 0, 1))} icon={Store} tone="violet" />
            <Stat label={t('discovery.list.relevance')} value={c.relevance != null ? `${Math.round(c.relevance * 100)}%` : '—'} hint={c.confidence != null ? t(`discovery.confidence.${c.confidence >= 0.75 ? 'high' : c.confidence >= 0.5 ? 'medium' : 'low'}`) : t('discovery.origin.manual')} icon={Globe} tone="success" />
          </div>

          <div className="apex-grid apex-grid--2">
            <Panel eyebrow={t('discovery.detail.profileEyebrow')} title={t('discovery.detail.profile')}>
              <dl className="competitor-facts">
                {c.address && <div><dt>{t('discovery.detail.address')}</dt><dd dir="auto">{c.address}</dd></div>}
                {c.phone && <div><dt>{t('discovery.detail.phone')}</dt><dd><a href={`tel:${c.phone.replace(/\s/g, '')}`} dir="ltr"><Phone size={12} aria-hidden="true" /> {c.phone}</a></dd></div>}
                {c.website_url && <div><dt>{t('market.detail.website')}</dt><dd><a href={safeHref(c.website_url)} target="_blank" rel="noreferrer noopener" dir="ltr">{c.website_url.replace(/^https?:\/\/(www\.)?/, '')} <ExternalLink size={11} aria-hidden="true" /></a></dd></div>}
                {c.categories.length > 0 && <div><dt>{t('discovery.detail.categories')}</dt><dd className="competitor-facts__chips">{c.categories.slice(0, 6).map((cat) => <Pill key={cat}>{cat.replace(/^[a-z]+=/, '').replace(/_/g, ' ')}</Pill>)}</dd></div>}
                {c.first_seen_at && <div><dt>{t('discovery.detail.firstSeen')}</dt><dd>{date.format(new Date(c.first_seen_at))}</dd></div>}
                {c.last_seen_at && <div><dt>{t('discovery.detail.lastSeen')}</dt><dd>{date.format(new Date(c.last_seen_at))}</dd></div>}
              </dl>
              {c.reasons.length > 0 && (
                <>
                  <h3 className="competitor-facts__heading">{t('discovery.detail.why')}</h3>
                  <ul className="competitor-reasons">{c.reasons.map((r) => <li key={r.code}>{reasonText(t, number, r)}</li>)}</ul>
                </>
              )}
              {c.relevance != null && <Meter value={Math.round(c.relevance * 100)} max={100} label={t('discovery.list.relevance')} />}
            </Panel>

            <Panel eyebrow={t('discovery.detail.sourcesEyebrow')} title={t('discovery.detail.sources')} subtitle={t('discovery.detail.sourcesHint')}>
              {c.source_records?.length ? (
                <ul className="competitor-source-list">
                  {c.source_records.map((s, index) => (
                    <li key={`${s.source}-${index}`}>
                      <div>
                        <strong>{t(`discovery.sources.${s.source}`)}</strong>
                        {s.name && <span className="apex-muted" dir="auto"> · {s.name}</span>}
                        {s.address && <div className="apex-muted" dir="auto">{s.address}</div>}
                        {s.description && <p className="competitor-source-list__about" dir="auto">{s.description}</p>}
                        <div className="apex-muted">{t('discovery.detail.seen', { date: date.format(new Date(s.last_seen_at)) })}</div>
                      </div>
                      {s.url && <a className="apex-chip" href={safeHref(s.url)} target="_blank" rel="noreferrer noopener">{t('discovery.detail.open')} <ExternalLink size={11} aria-hidden="true" /></a>}
                    </li>
                  ))}
                </ul>
              ) : <StateBlock compact title={t('discovery.detail.addedByYou')} />}
              {c.profiles?.length > 0 && (
                <div className="competitor-profiles">
                  <strong>{t('discovery.detail.profiles')}</strong>
                  <div>
                    {c.profiles.map((link) => (
                      <a key={link} className="apex-chip" href={safeHref(link)} target="_blank" rel="noreferrer noopener">
                        {profileLabel(link)} <ExternalLink size={11} aria-hidden="true" />
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </Panel>
          </div>

          <CompetitorIntel competitor={c} t={t} locale={locale} />

          {c.is_tracked && <DataCompleteness completeness={dataStatus.data} competitorId={competitorId} queued={Boolean(dataStatus.data?.queued)} />}
          {c.is_tracked && <CompetitorComments competitorId={competitorId} />}

          {c.is_tracked && (
            <Panel eyebrow={t('discovery.detail.pricesEyebrow')} title={t('market.detail.priceComparison')} subtitle={t('market.detail.priceComparisonSubtitle')} bodyClassName="is-flush">
              {profile.isPending ? <StateBlock kind="loading" compact title={t('common.loading')} /> : comparisons.length ? (
                <div className="apex-table-wrap"><table className="apex-table"><thead><tr><th>{t('market.detail.productName')}</th><th className="apex-table__num">{t('market.detail.yourPrice')}</th><th className="apex-table__num">{t('market.detail.theirPrice')}</th></tr></thead>
                  <tbody>{comparisons.map((row) => <tr key={row.product_name}><td>{row.product_name}</td><td className="apex-table__num">{money(row.your_price, row.currency)}</td><td className="apex-table__num">{money(row.their_price, row.currency)}</td></tr>)}</tbody></table></div>
              ) : <StateBlock compact title={t('market.empty.priceComparisonTitle')} description={t('market.empty.priceComparisonDescription')} />}
              {(strengths.length > 0 || weaknesses.length > 0) && (
                <div className="competitor-traits">
                  {strengths.length > 0 && <div><h3>{t('market.detail.strengths')}</h3><ul>{strengths.map((s) => <li key={s}>{s}</li>)}</ul></div>}
                  {weaknesses.length > 0 && <div><h3>{t('market.detail.weaknesses')}</h3><ul>{weaknesses.map((s) => <li key={s}>{s}</li>)}</ul></div>}
                </div>
              )}
            </Panel>
          )}
          {c.is_tracked && <RecordCompetitorPrice competitorId={competitorId} t={t} />}
        </div>
      </BusinessPageContainer>
    </DashboardLayout>
  );
}

export default CompetitorProfileDetailPage;
