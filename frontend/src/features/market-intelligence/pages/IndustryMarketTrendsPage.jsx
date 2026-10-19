import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { DashboardLayout } from '../../../app/layouts/DashboardLayout.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import { MarketTabs } from '../components/MarketTabs.jsx';
import { MarketOverviewCards } from '../components/MarketOverviewCards.jsx';
import { MarketInsights } from '../components/MarketInsights.jsx';
import { MarketStructure } from '../components/MarketStructure.jsx';
import { useMarketOverview } from '../hooks/useMarketOverview.js';
import '../styles/MarketIntelligence.css';

// This page used to be 100% fabricated static content (a fake YoY price
// chart, a fake seasonal bar chart, a fake "Bullish 75%" card, a fake
// ranked emerging-trends list, a fake market-signals table). None of
// that has a real backend signal (no year-over-year benchmark, no
// seasonal decomposition, no trend-ranking model exists anywhere in this
// platform). The only real, tenant-wide signals this platform actually
// computes for an "industry trends" view are the same 3 honest
// aggregates the Market Intelligence Overview page's cards use
// (backend/src/ai/dashboard/market_overview.py) - shown here via the
// same shared MarketOverviewCards component. A shorter, honest page is
// correct; nothing here is replaced with a different invented number.
export function IndustryMarketTrendsPage() {
  const { t } = useI18n();
  const query = useMarketOverview();

  return <DashboardLayout><div className="market-page">
    <PageHeader title={t('market.industry.title')} subtitle={t('market.industry.subtitle')} />
    <MarketTabs />
    {query.isPending
      ? <div aria-busy="true"><Skeleton height="103px" variant="rectangular" /><Skeleton height="220px" variant="rectangular" /></div>
      : query.isError
        ? <EmptyState title={t('market.industry.errorTitle')} description={t('market.industry.errorDescription')} action={<Button size="sm" variant="outline" onClick={() => query.refetch()}>{t('marketMain.actions.retry')}</Button>} />
        : <MarketOverviewCards marketOverview={query.data} t={t} />}
    <MarketStructure />
    <MarketInsights />
  </div></DashboardLayout>;
}
