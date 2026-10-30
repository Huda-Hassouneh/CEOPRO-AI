import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Search } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { DashboardLayout } from '../../../app/layouts/DashboardLayout.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Card from '../../../shared/components/ui/Card.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import Badge from '../../../shared/components/ui/Badge.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { MarketTabs } from '../components/MarketTabs.jsx';
import { MarketPerceptionPanel } from '../components/MarketPerceptionPanel.jsx';
import { useCompetitors } from '../hooks/useCompetitors.js';
import '../styles/MarketIntelligence.css';

// This page used to rank a fully fabricated "24 competitors industry-
// wide" leaderboard (Stratos Analytics, Nova Insights, ...) with fake
// movement deltas. It now ranks this tenant's own REAL tracked
// competitors from GET /competitors (backend/src/ai/dashboard/
// competitors.py) by relevance_score - the same real composite score
// that module's own docstring documents (price competitiveness 45% /
// sentiment 35% / market activity 20%, renormalized across whichever
// signals are actually available). There is no real per-period
// historical data anywhere in this backend, so the old "Trend"/
// "Movement" column and the "Score Breakdown"/"Key Insights"/"Top
// Movers" sections (which all depended on one) are removed rather than
// fed a different invented number.
const scoreVariant = (value, highThreshold, lowThreshold) => {
  if (value == null) return 'neutral';
  if (value >= highThreshold) return 'light-success';
  if (value <= lowThreshold) return 'error';
  return 'warning';
};

export function MarketLeaderboardPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { data, isLoading, isError, refetch } = useCompetitors();
  const [sort, setSort] = useState('relevance');
  const [query, setQuery] = useState('');
  const competitors = useMemo(() => data?.competitors ?? [], [data]);

  const rows = useMemo(() => {
    const key = sort === 'price' ? 'price_competitiveness' : 'relevance_score';
    return competitors
      .filter((row) => row.name.toLowerCase().includes(query.toLowerCase()))
      .slice()
      .sort((a, b) => (b[key] ?? -Infinity) - (a[key] ?? -Infinity));
  }, [competitors, sort, query]);

  const scoredCompetitors = competitors.filter((row) => row.relevance_score != null);
  const averageRelevance = scoredCompetitors.length
    ? scoredCompetitors.reduce((sum, row) => sum + row.relevance_score, 0) / scoredCompetitors.length
    : null;

  const header = <PageHeader title={t('market.final.leaderboardTitle')} subtitle={t('market.reference.leaderboardSubtitle')} />;

  if (isLoading) {
    return <DashboardLayout><div className="market-page leaderboard-reference-page">{header}<MarketTabs /><div aria-busy="true"><Skeleton height="90px" variant="rectangular" /><Skeleton height="320px" variant="rectangular" /></div></div></DashboardLayout>;
  }
  if (isError) {
    return <DashboardLayout><div className="market-page leaderboard-reference-page">{header}<MarketTabs /><EmptyState title={t('market.competitorsPage.errorTitle')} description={t('market.competitorsPage.errorDescription')} action={<Button size="sm" variant="outline" onClick={() => refetch()}>{t('market.competitorsPage.retry')}</Button>} /></div></DashboardLayout>;
  }

  return <DashboardLayout><div className="market-page leaderboard-reference-page">
    {header}
    <MarketTabs />
    <MarketPerceptionPanel t={t} />
    <section className="reference-kpi-grid">
      <Card className="reference-kpi"><small>{t('market.reference.totalCompetitors')}</small><strong>{competitors.length}</strong></Card>
      <Card className="reference-kpi"><small>{t('marketScoped.leaderboard.compositeScore')}</small><strong>{averageRelevance != null ? `${averageRelevance.toFixed(1)} / 100` : '—'}</strong></Card>
    </section>
    <div className="leaderboard-filter-row">
      <select value={sort} onChange={(event) => setSort(event.target.value)} aria-label={t('marketScoped.leaderboard.sort')}>
        <option value="relevance">{t('marketScoped.leaderboard.compositeScore')}</option>
        <option value="price">{t('marketScoped.leaderboard.priceScore')}</option>
      </select>
      <label><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('marketScoped.leaderboard.search')} aria-label={t('marketScoped.leaderboard.search')} /></label>
    </div>
    <section className="market-panel leaderboard-table-panel">
      {rows.length === 0
        ? <EmptyState title={t('market.competitorsPage.emptyTitle')} description={t('market.competitorsPage.emptyDescription')} action={<Button size="sm" leadingIcon={<Plus size={15} />} onClick={() => navigate(routePaths.marketAddCompetitor)}>{t('market.controls.addCompetitor')}</Button>} />
        : <div className="market-table-wrap"><table className="market-table"><thead><tr>
          <th>{t('marketScoped.leaderboard.competitor')}</th>
          <th>{t('market.competitorsPage.tier')}</th>
          <th>{t('marketScoped.leaderboard.priceScore')}</th>
          <th>{t('market.detail.sentiment')}</th>
          <th>{t('marketScoped.leaderboard.activityScore')}</th>
          <th>{t('marketScoped.leaderboard.compositeScore')}</th>
          <th>{t('marketScoped.common.actions')}</th>
        </tr></thead><tbody>{rows.map((row) => <tr key={row.id}>
          <td><span className="market-entity-logo">{row.name.charAt(0)}</span><strong>{row.name}</strong></td>
          <td>{row.tier === 'STRATEGIC' ? t('market.competitorsPage.tierStrategic') : t('market.competitorsPage.tierRelevant')}</td>
          <td><Badge variant={scoreVariant(row.price_competitiveness, 7, 4)}>{row.price_competitiveness != null ? `${row.price_competitiveness.toFixed(1)}/10` : '—'}</Badge></td>
          <td>{row.market_sentiment_label ? <Badge variant={row.market_sentiment_label === 'Positive' ? 'light-success' : row.market_sentiment_label === 'Negative' ? 'error' : 'warning'}>{t(`market.status.${row.market_sentiment_label.toLowerCase()}`)}</Badge> : '—'}</td>
          <td><Badge variant={row.market_activity === 'High' ? 'light-success' : row.market_activity === 'Low' ? 'neutral' : 'warning'}>{t(`market.status.${row.market_activity.toLowerCase()}`)}</Badge></td>
          <td>{row.relevance_score != null ? <span className="leaderboard-score"><strong>{row.relevance_score.toFixed(1)}</strong><i><b style={{ width: `${row.relevance_score}%` }} /></i></span> : '—'}</td>
          <td><button type="button" className="market-table-action" onClick={() => navigate(`${routePaths.marketCompetitors}/${row.id}`)}>{t('marketScoped.common.viewDetails')}</button></td>
        </tr>)}</tbody></table></div>}
    </section>
  </div></DashboardLayout>;
}
