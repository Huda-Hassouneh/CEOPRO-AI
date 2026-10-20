import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { Download } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { DashboardLayout } from '../../../app/layouts/DashboardLayout.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { PositionPill, TIERS, TierPill } from '../components/PriceLadder.jsx';
import { reportCsv } from '../lib/reportCsv.js';
import { usePriceComparisonReport } from '../hooks/usePriceComparisons.js';
import '../styles/Pricing.css';

// GET /reports/price-comparison: every product that has competitor evidence, with its tiers and (for added-value-only
// products) the justified range. Similar and added-value items are labelled as references, never as exact prices.
export function PriceComparisonReportPage() {
  const { t, locale } = useI18n();
  const query = usePriceComparisonReport(200);
  const number = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  const money = (amount, currency) => (amount == null ? '—' : new Intl.NumberFormat(locale, { style: 'currency', currency }).format(amount));
  const products = query.data?.products ?? [];

  const download = () => {
    const url = URL.createObjectURL(new Blob(['\uFEFF', reportCsv(products)], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'price-comparison.csv';
    link.click();
    URL.revokeObjectURL(url);
  };

  return <DashboardLayout><div className="pricing-page pricing-report">
    <PageHeader title={t('pricing.report.title')} subtitle={t('pricing.report.subtitle')} actions={<>
      <Link to={routePaths.pricing}>{t('pricing.report.back')}</Link>
      <Button size="sm" variant="outline" onClick={download} disabled={products.length === 0}><Download size={14} aria-hidden="true" /> {t('pricing.report.download')}</Button>
    </>} />
    {query.isPending && <Skeleton />}
    {query.isError && <EmptyState title={t('pricing.report.loadError')} />}
    {query.isSuccess && products.length === 0 && <EmptyState title={t('pricing.report.empty')} />}
    {query.isSuccess && products.length > 0 && (
      <div className="apex-table-wrap pricing-report__table-wrap"><table className="apex-table">
        <thead><tr>
          <th>{t('pricing.report.product')}</th><th className="apex-table__num">{t('pricing.report.yourPrice')}</th>
          <th>{t('pricing.report.bestTier')}</th><th>{t('pricing.report.counts')}</th>
          <th>{t('pricing.report.position')}</th><th>{t('pricing.report.range')}</th>
        </tr></thead>
        <tbody>{products.map((p) => (
          <tr key={p.product_id}>
            <td>{p.name}</td>
            <td className="apex-table__num">{money(p.your_price, p.currency)}</td>
            <td><TierPill tier={p.headline.tier} t={t} /></td>
            <td>{TIERS.filter((tier) => p.tiers[tier].count).map((tier) => <span key={tier} className="pricing-coverage__item"><TierPill tier={tier} t={t} /> <strong>{number.format(p.tiers[tier].count)}</strong></span>)}</td>
            <td>{p.headline.tier === 'ADDED_VALUE' ? <span className="apex-muted">—</span> : <PositionPill pct={p.headline.position_pct} t={t} number={number} />}</td>
            <td>{p.added_value_guidance
              ? <span>{money(p.added_value_guidance.range_low, p.currency)} – {money(p.added_value_guidance.range_high, p.currency)} <span className="apex-muted">({t(`pricing.ladder.guidance.position.${p.added_value_guidance.position}`)})</span></span>
              : <span className="apex-muted">—</span>}</td>
          </tr>))}
        </tbody>
      </table></div>
    )}
  </div></DashboardLayout>;
}

export default PriceComparisonReportPage;
