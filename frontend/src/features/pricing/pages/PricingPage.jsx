import { useEffect, useMemo, useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Search, Tag } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { DashboardLayout } from '../../../app/layouts/DashboardLayout.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import { Pager } from '../../../shared/components/apex/Apex.jsx';
import { useDebounce } from '../../../shared/hooks/useDebounce.js';
import { productsApi } from '../../products/api/productsApi.js';
import { PriceRecommendationModal } from '../components/PriceRecommendationModal.jsx';
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

  return <DashboardLayout><div className="pricing-page">
    <PageHeader title={t('pricing.page.title')} subtitle={t('pricing.page.subtitle')} />
    <div className="pricing-filters">
      <Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t('pricing.list.searchPlaceholder')} leftIcon={<Search size={17} />} aria-label={t('pricing.list.searchPlaceholder')} />
    </div>

    {query.isPending && <Skeleton height="320px" variant="rectangular" />}
    {query.isError && <EmptyState title={t('pricing.list.loadError')} action={<Button size="sm" variant="outline" onClick={() => query.refetch()}>{t('pricing.list.retry')}</Button>} />}
    {query.isSuccess && (filtered.length
      ? <div className="pricing-table-wrap"><table className="pricing-table">
          <thead><tr><th>{t('pricing.table.product')}</th><th>{t('pricing.table.currentPrice')}</th><th>{t('pricing.table.cost')}</th><th>{t('pricing.table.markup')}</th><th>{t('pricing.table.actions')}</th></tr></thead>
          <tbody>{filtered.map((product) => {
            const markup = markupOverCostPct(product.current_price, product.cost_price);
            return <tr key={product.product_id}>
              <td><strong>{product.product_name}</strong>{product.brand && <span className="pricing-table-sub">{product.brand}</span>}</td>
              <td>{currencyFormatter(product.current_price, product.currency)}</td>
              <td>{currencyFormatter(product.cost_price, product.currency)}</td>
              <td>{markup != null ? `${percentFormatter.format(markup)}%` : t('products.common.notAvailable')}</td>
              <td><button type="button" className="pricing-link-action" onClick={() => setActiveProduct(product)}><Tag size={13} />{t('pricing.list.getRecommendation')}</button></td>
            </tr>;
          })}</tbody>
        </table>
        <Pager page={page} pageSize={PAGE_SIZE} total={total} onChange={setPage} t={t} dir={dir} number={percentFormatter} busy={query.isFetching} />
        </div>
      : <EmptyState
          title={t(term ? 'pricing.list.noResultsTitle' : 'pricing.list.emptyTitle')}
          description={t(term ? 'pricing.list.noResultsDescription' : 'pricing.list.emptyDescription')}
        />)}

    <PriceRecommendationModal open={Boolean(activeProduct)} product={activeProduct} onClose={() => setActiveProduct(null)} currencyFormatter={currencyFormatter} t={t} />
  </div></DashboardLayout>;
}
