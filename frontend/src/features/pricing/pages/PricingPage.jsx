import { useEffect, useMemo, useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { GitCompareArrows, History, RefreshCw, Search, Tag } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { DashboardLayout } from '../../../app/layouts/DashboardLayout.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import { Pager, Pill } from '../../../shared/components/apex/Apex.jsx';
import Toast from '../../../shared/components/ui/Toast.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useDebounce } from '../../../shared/hooks/useDebounce.js';
import { productsApi } from '../../products/api/productsApi.js';
import { PriceRecommendationModal } from '../components/PriceRecommendationModal.jsx';
import { PriceRecommendationHistoryModal } from '../components/PriceRecommendationHistoryModal.jsx';
import { PriceComparisonModal } from '../components/PriceComparisonModal.jsx';
import { PositionPill, TIERS, TierPill } from '../components/PriceLadder.jsx';
import { usePriceComparisonSummary, useRefreshComparisons } from '../hooks/usePriceComparisons.js';
import { coverageBucket, marketPosition } from '../api/marketPosition.js';
import '../styles/Pricing.css';

// Margin here is computed the same way backend/src/ai/pricing/
// guardrails.py::apply_margin_guardrail() defines it - markup over cost
// ((price - cost) / cost), not the more common margin-over-price
// definition, to match the real number the pricing recommendation's own
// margin guardrail actually protects, not a different formula that would
// silently disagree with it. Never computed at all when cost_price is
// unset (nullable, frequently unset) - never a fabricated cost of 0.
const PAGE_SIZE = 25;

function markupOverCostPct(price, cost) {
  if (cost == null || cost <= 0) return null;
  return ((price - cost) / cost) * 100;
}

export function PricingPage() {
  const { t, locale, dir } = useI18n();
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const term = useDebounce(search.trim(), 300);
  useEffect(() => setPage(0), [term]);
  // Searched and paged on the server, so every product is reachable however
  // large the catalogue is.
  const query = useQuery({
    queryKey: ['products', 'page', term, page, PAGE_SIZE],
    queryFn: () => productsApi.list({ limit: PAGE_SIZE, offset: page * PAGE_SIZE, search: term || undefined }),
    placeholderData: keepPreviousData,
  });
  const [activeProduct, setActiveProduct] = useState(null);
  const [historyProduct, setHistoryProduct] = useState(null);
  const [compareProduct, setCompareProduct] = useState(null);
  const [notice, setNotice] = useState(null);

  // One formatter cache per interface language.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const currencyCache = useMemo(() => new Map(), [locale]);
  const currencyFormatter = (amount, currency) => {
    if (amount == null || !currency) return t('products.common.notAvailable');
    if (!currencyCache.has(currency)) currencyCache.set(currency, new Intl.NumberFormat(locale, { style: 'currency', currency }));
    return currencyCache.get(currency).format(amount);
  };
  const percentFormatter = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);

  const filtered = query.data?.products ?? [];
  const total = query.data?.total ?? 0;

  // How each product on this page relates to what competitors sell (exact / equivalent / similar / added value).
  const comparisons = usePriceComparisonSummary(filtered.map((product) => product.product_id));
  const refresh = useRefreshComparisons();
  const summaries = comparisons.data ?? {};
  const coverage = useMemo(() => {
    const counts = { estimate: 0, none: 0 };
    TIERS.forEach((tier) => { counts[tier] = 0; });
    filtered.forEach((product) => {
      counts[coverageBucket(summaries[product.product_id])] += 1;
    });
    return counts;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtered, comparisons.data]);
  const refreshComparisons = () => refresh.mutate(undefined, {
    onSuccess: (result) => setNotice({ variant: 'success', message: t(result.ai_pending ? 'pricing.ladder.refreshedPending' : 'pricing.ladder.refreshed', { rows: result.rows, competitors: result.competitors, pending: result.ai_pending }) }),
    onError: () => setNotice({ variant: 'error', message: t('pricing.ladder.refreshFailed') }),
  });

  return <DashboardLayout><div className="pricing-page">
    <PageHeader title={t('pricing.page.title')} subtitle={t('pricing.page.subtitle')} />
    <div className="pricing-toolbar">
    <div className="pricing-filters">
      <Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t('pricing.list.searchPlaceholder')} leftIcon={<Search size={17} />} aria-label={t('pricing.list.searchPlaceholder')} />
    </div>
    <Button size="sm" variant="outline" onClick={refreshComparisons} loading={refresh.isPending} loadingLabel={t('pricing.ladder.refreshing')}><RefreshCw size={14} aria-hidden="true" /> {t('pricing.ladder.refresh')}</Button>
    <Link className="pricing-link" to={routePaths.pricingReport}>{t('pricing.report.open')}</Link>
    </div>

    {query.isSuccess && filtered.length > 0 && comparisons.isSuccess && (
      <div className="pricing-coverage" role="group" aria-label={t('pricing.ladder.coverageTitle')}>
        <span className="pricing-coverage__title">{t('pricing.ladder.coverageTitle')}</span>
        {TIERS.map((tier) => <span key={tier} className="pricing-coverage__item"><TierPill tier={tier} t={t} /> <strong>{percentFormatter.format(coverage[tier])}</strong></span>)}
        <span className="pricing-coverage__item"><Pill tone="neutral">{t('pricing.ladder.estimate.label')}</Pill> <strong>{percentFormatter.format(coverage.estimate)}</strong></span>
        <span className="pricing-coverage__item"><Pill tone="warning">{t('pricing.ladder.estimate.noMarketData')}</Pill> <strong>{percentFormatter.format(coverage.none)}</strong></span>
      </div>
    )}

    {query.isPending && <Skeleton height="320px" variant="rectangular" />}
    {query.isError && <EmptyState title={t('pricing.list.loadError')} action={<Button size="sm" variant="outline" onClick={() => query.refetch()}>{t('pricing.list.retry')}</Button>} />}
    {query.isSuccess && (filtered.length
      ? <div className="pricing-table-wrap"><table className="pricing-table">
          <thead><tr><th>{t('pricing.table.product')}</th><th>{t('pricing.table.currentPrice')}</th><th>{t('pricing.table.cost')}</th><th>{t('pricing.table.markup')}</th><th>{t('pricing.table.position')}</th><th>{t('pricing.table.actions')}</th></tr></thead>
          <tbody>{filtered.map((product) => {
            const markup = markupOverCostPct(product.current_price, product.cost_price);
            const position = marketPosition(summaries[product.product_id]);
            const headline = position.headline;
            return <tr key={product.product_id}>
              <td><strong dir="auto">{product.product_name}</strong>{product.brand && <span className="pricing-table-sub">{product.brand}</span>}</td>
              <td>{currencyFormatter(product.current_price, product.currency)}</td>
              <td>{currencyFormatter(product.cost_price, product.currency)}</td>
              <td>{markup != null ? `${percentFormatter.format(markup)}%` : t('products.common.notAvailable')}</td>
              <td className="pricing-position">
                {comparisons.isPending ? <span className="apex-muted">…</span> : headline
                  ? <><TierPill tier={headline.tier} t={t} /> <PositionPill pct={headline.position_pct} t={t} number={percentFormatter} /><span className="pricing-table-sub">{t('pricing.ladder.basedOn', { count: headline.count })}{headline.tier === 'SIMILAR' && (headline.direction === 'own_richer' || headline.direction === 'own_leaner') ? ` · ${t(`pricing.ladder.direction.${headline.direction}`)}` : ''}</span></>
                  : position.kind === 'estimate'
                    ? <><Pill tone="neutral">{t('pricing.ladder.estimate.label')}</Pill> <PositionPill pct={position.pct} t={t} number={percentFormatter} /><span className="pricing-table-sub">{t(`pricing.ladder.estimate.basis.${position.basis}`)} · {t('pricing.ladder.estimate.marketPrice', { price: currencyFormatter(position.marketPrice, product.currency) })}</span></>
                    : <><span className="apex-muted">{t('pricing.ladder.estimate.noMarketData')}</span><span className="pricing-table-sub">{t('pricing.ladder.estimate.noMarketDataHint')}</span></>}
              </td>
              <td className="pricing-actions">
                <button type="button" className="pricing-link-action" onClick={() => setCompareProduct(product)}><GitCompareArrows size={13} />{t('pricing.list.compare')}</button>
                <button type="button" className="pricing-link-action" onClick={() => setActiveProduct(product)}><Tag size={13} />{t('pricing.list.getRecommendation')}</button>
                <button type="button" className="pricing-link-action" onClick={() => setHistoryProduct(product)}><History size={13} />{t('pricing.list.history')}</button>
              </td>
            </tr>;
          })}</tbody>
        </table>
        <Pager page={page} pageSize={PAGE_SIZE} total={total} onChange={setPage} t={t} dir={dir} number={percentFormatter} busy={query.isFetching} />
        </div>
      : <EmptyState
          title={t(term ? 'pricing.list.noResultsTitle' : 'pricing.list.emptyTitle')}
          description={t(term ? 'pricing.list.noResultsDescription' : 'pricing.list.emptyDescription')}
        />)}

    <PriceComparisonModal open={Boolean(compareProduct)} product={compareProduct} onClose={() => setCompareProduct(null)} t={t} />
    <PriceRecommendationHistoryModal open={Boolean(historyProduct)} product={historyProduct} onClose={() => setHistoryProduct(null)} t={t} locale={locale} />
    {notice && <Toast variant={notice.variant} message={notice.message} onClose={() => setNotice(null)} />}
    <PriceRecommendationModal open={Boolean(activeProduct)} product={activeProduct} onClose={() => setActiveProduct(null)} currencyFormatter={currencyFormatter} t={t} />
  </div></DashboardLayout>;
}
