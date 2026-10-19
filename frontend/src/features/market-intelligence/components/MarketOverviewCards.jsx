import Badge from '../../../shared/components/ui/Badge.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import { MarketMetricCard } from './MarketMetricCard.jsx';
import { MarketIntelligenceSection } from './MarketIntelligenceSection.jsx';
import { MarketIntelligenceTable } from './MarketIntelligenceTable.jsx';

const LEVEL_VARIANT = { High: 'light-success', Medium: 'warning', Low: 'neutral' };

// Every field rendered here is real - backend/src/ai/dashboard/
// market_overview.py's own module docstring explains exactly what each
// of these three honest aggregates is (and isn't). direction/label/
// positive_pct come back null, and category_activity comes back {},
// when there isn't enough real signal yet; this component always shows
// that as an explicit "not enough data yet" state, never a fabricated
// default value or trend.
export function MarketOverviewCards({ marketOverview, t }) {
  const priceTrend = marketOverview?.price_trend;
  const sentiment = marketOverview?.sentiment;
  const categoryEntries = Object.entries(marketOverview?.category_activity || {});

  const cards = [
    {
      labelKey: 'marketMain.overviewCards.priceTrend',
      value: priceTrend?.direction ? t(`marketMain.overviewCards.direction${priceTrend.direction}`) : t('market.common.notAvailable'),
      icon: 'growth',
      tone: priceTrend?.direction === 'Down' ? 'red' : priceTrend?.direction === 'Up' ? 'green' : 'purple',
      trend: priceTrend ? `${priceTrend.increases} ${t('marketMain.overviewCards.increases')} · ${priceTrend.decreases} ${t('marketMain.overviewCards.decreases')}` : '',
      trendKey: priceTrend?.direction ? 'market.empty.noTrend' : 'marketMain.overviewCards.notEnoughData',
    },
    {
      labelKey: 'marketMain.overviewCards.sentiment',
      value: sentiment?.label ? t(`marketMain.overviewCards.sentiment${sentiment.label}`) : t('market.common.notAvailable'),
      icon: 'sentiment',
      tone: sentiment?.label === 'Bearish' ? 'red' : sentiment?.label === 'Bullish' ? 'green' : 'purple',
      trend: sentiment?.positive_pct != null ? `${sentiment.positive_pct}% ${t('marketMain.overviewCards.positive')} · ${sentiment.competitors_with_sentiment} ${t('marketMain.overviewCards.competitorsTracked')}` : '',
      trendKey: sentiment?.label ? 'market.empty.noTrend' : 'marketMain.overviewCards.notEnoughData',
    },
    {
      labelKey: 'marketMain.overviewCards.categoryActivity',
      value: categoryEntries.length ? String(categoryEntries.length) : t('market.common.notAvailable'),
      icon: 'activity',
      tone: 'blue',
      trend: '',
      trendKey: categoryEntries.length ? 'market.empty.noTrend' : 'marketMain.overviewCards.notEnoughData',
    },
  ];

  const categoryColumns = [
    { key: 'category', label: t('marketMain.overviewCards.categoryColumn') },
    {
      key: 'level',
      label: t('marketMain.overviewCards.levelColumn'),
      render: (row) => <Badge variant={LEVEL_VARIANT[row.level] || 'neutral'}>{t(`market.status.${row.level.toLowerCase()}`)}</Badge>,
    },
  ];
  const categoryRows = categoryEntries.map(([category, level]) => ({ id: category, category, level }));

  return <>
    <section className="market-metric-grid">{cards.map((item) => <MarketMetricCard key={item.labelKey} item={item} t={t} />)}</section>
    <MarketIntelligenceSection title={t('marketMain.overviewCards.categoryTableTitle')} subtitle={t('marketMain.overviewCards.categoryTableSubtitle')}>
      <MarketIntelligenceTable
        columns={categoryColumns}
        rows={categoryRows}
        emptyState={<EmptyState className="market-main-empty" title={t('marketMain.overviewCards.categoryEmptyTitle')} description={t('marketMain.overviewCards.categoryEmptyDescription')} />}
      />
    </MarketIntelligenceSection>
  </>;
}
