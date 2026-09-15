import { useMemo, useState } from 'react';
import { Filter, Plus, Search } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { DashboardLayout } from '../../../app/layouts/DashboardLayout.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { MarketTabs } from '../components/MarketTabs.jsx';
import { CompetitorTable } from '../components/CompetitorTable.jsx';
import { ActivityTimeline } from '../components/ActivityTimeline.jsx';
import { competitorRows, previewCompetitors } from '../config/competitorPreviewData.js';
import { competitorActivity } from '../config/marketPreviewData.js';
import '../styles/MarketIntelligence.css';

export function CompetitorsPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [rows] = useState(() => [...previewCompetitors, ...competitorRows]);
  const [query, setQuery] = useState('');
  const [industry, setIndustry] = useState('all');
  const [status, setStatus] = useState('all');
  const [sort, setSort] = useState('updated');
  const [page, setPage] = useState(1);
  const filteredRows = useMemo(() => {
    const next = rows.filter((row) => (!query || `${row[0]} ${row[1]}`.toLowerCase().includes(query.toLowerCase())) && (industry === 'all' || row[2] === industry) && (status === 'all' || row[5] === status));
    return sort === 'name' ? [...next].sort((a, b) => a[0].localeCompare(b[0])) : next;
  }, [rows, query, industry, status, sort]);
  const visibleRows = filteredRows.slice((page - 1) * 10, page * 10);
  return <DashboardLayout><div className="market-page competitors-page">
    <PageHeader title={t('market.competitorsPage.title')} subtitle={t('market.competitorsPage.subtitle')} actions={<Button size="sm" leadingIcon={<Plus size={15} />} onClick={() => navigate(routePaths.marketAddCompetitor)}>{t('market.controls.addCompetitor')}</Button>} />
    <MarketTabs />
    <div className="competitor-filters"><Input value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder={t('market.competitorsPage.search')} leftIcon={<Search size={17} />} aria-label={t('market.competitorsPage.search')} /><select value={industry} onChange={(event) => setIndustry(event.target.value)} aria-label={t('market.competitorsPage.industry')}><option value="all">{t('market.competitorsPage.allIndustries')}</option><option>Telecom</option><option>Internet</option><option>Analytics</option></select><select value={status} onChange={(event) => setStatus(event.target.value)} aria-label={t('market.competitorsPage.status')}><option value="all">{t('market.competitorsPage.allStatus')}</option><option value="market.status.high">{t('market.status.high')}</option><option value="market.status.medium">{t('market.status.medium')}</option><option value="market.status.low">{t('market.status.low')}</option></select><select value={sort} onChange={(event) => setSort(event.target.value)} aria-label={t('market.competitorsPage.sort')}><option value="updated">{t('market.competitorsPage.lastUpdated')}</option><option value="name">{t('market.competitorsPage.name')}</option></select><Button variant="outline" leadingIcon={<Filter size={16} />}>{t('market.competitorsPage.filter')}</Button></div>
    <section className="market-panel competitor-list-panel"><CompetitorTable t={t} rows={visibleRows} onDetails={(name) => navigate(`${routePaths.marketCompetitors}/${encodeURIComponent(name.toLowerCase().replace(/\s+/g, '-'))}`)} /><div className="competitor-pagination"><span>{t('market.competitorsPage.showing', { start: filteredRows.length ? (page - 1) * 10 + 1 : 0, end: Math.min(page * 10, filteredRows.length), total: filteredRows.length })}</span><div><button type="button" disabled={page === 1} onClick={() => setPage((value) => value - 1)} aria-label={t('market.competitorsPage.previous')}>‹</button><button type="button" className="is-current" aria-current="page">{page}</button><button type="button" disabled={page * 10 >= filteredRows.length} onClick={() => setPage((value) => value + 1)} aria-label={t('market.competitorsPage.next')}>›</button></div></div></section>
    <section className="market-panel competitor-activity-panel"><div className="market-panel__header"><div><h2>{t('market.overview.activityTitle')}</h2><p>{t('market.overview.activitySubtitle')}</p></div><button type="button" className="market-link">{t('market.controls.viewAll')}</button></div><ActivityTimeline t={t} items={competitorActivity} /></section>
  </div></DashboardLayout>;
}
