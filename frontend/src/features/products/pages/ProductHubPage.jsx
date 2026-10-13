import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  AlertTriangle, ArrowLeft, Boxes, CalendarRange, Coins, ExternalLink, Megaphone, MessageSquareText,
  Pencil, ShoppingCart, Sparkles, Star, Tag, TrendingDown, TrendingUp, Users,
} from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { DashboardLayout } from '../../../app/layouts/DashboardLayout.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import BusinessPageContainer from '../../../shared/components/layout/BusinessPageContainer.jsx';
import { ApexButton, Delta, Meter, Panel, Pill, Stat, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import ForecastChart from '../../../shared/components/charts/ForecastChart.jsx';
import Toast from '../../../shared/components/ui/Toast.jsx';
import httpClient from '../../../shared/lib/httpClient.js';
import { QuickSaleModal } from '../components/QuickSaleModal.jsx';
import { PriceRecommendationModal } from '../../pricing/components/PriceRecommendationModal.jsx';

const TONE_ICON = { restock: Boxes, overstock: Boxes, sales_down: TrendingDown, sales_up: TrendingUp, no_recent_sales: AlertTriangle, priced_above: Tag, priced_below: Tag, no_competitor_prices: Users, competitor_price_change: Tag, negative_reviews: MessageSquareText };

export function useProductIntelligence(productId) {
  return useQuery({
    queryKey: ['product-intelligence', productId],
    queryFn: async () => (await httpClient.get(`/dashboard/products/${encodeURIComponent(productId)}/intelligence`)).data,
    enabled: Boolean(productId),
    retry: (count, error) => error?.response?.status !== 404 && count < 1,
  });
}

export function ProductHubPage() {
  const { productId } = useParams();
  const { t, locale, dir } = useI18n();
  const navigate = useNavigate();
  const query = useProductIntelligence(productId);
  const [saleOpen, setSaleOpen] = useState(false);
  const [priceOpen, setPriceOpen] = useState(false);
  const [notice, setNotice] = useState(null);

  const number = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  const money = (amount, currency, digits) => (amount == null || !currency ? '—' : new Intl.NumberFormat(locale, { style: 'currency', currency, ...(digits != null ? { maximumFractionDigits: digits } : {}) }).format(amount));
  const date = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }), [locale]);
  const fmtDate = (value) => (value ? date.format(new Date(value)) : '—');

  const back = <button type="button" className="apex-back" onClick={() => navigate(routePaths.products)}><ArrowLeft size={15} aria-hidden="true" className="apex-flip-rtl" />{t('productHub.back')}</button>;

  if (query.isPending) return <DashboardLayout><BusinessPageContainer>{back}<div className="apex-page"><Panel><StateBlock kind="loading" title={t('common.loading')} /></Panel><div className="apex-grid apex-grid--stats">{[0, 1, 2, 3].map((i) => <Panel key={i}><StateBlock kind="loading" compact /></Panel>)}</div></div></BusinessPageContainer></DashboardLayout>;
  if (query.isError) {
    const missing = query.error?.response?.status === 404;
    return <DashboardLayout><BusinessPageContainer>{back}<Panel><StateBlock kind={missing ? 'empty' : 'error'} title={missing ? t('productHub.notFound') : t('productHub.loadError')} onRetry={missing ? undefined : () => query.refetch()} retryLabel={t('demandApex.actions.retry')} action={missing ? <ApexButton onClick={() => navigate(routePaths.products)}>{t('productHub.back')}</ApexButton> : null} /></Panel></BusinessPageContainer></DashboardLayout>;
  }

  const { product, sales, demand, competitors, reviews, signals } = query.data;
  const currency = product.currency;
  const stock = demand.stock;
  const listProduct = { product_id: product.product_id, product_name: product.display_name, current_price: product.current_price, currency, stock_quantity: stock.current };
  const currencyFormatter = (amount, cur) => money(amount, cur);
  const market = competitors.market;

  const signalText = (signal) => {
    const values = { ...signal, pct: signal.pct != null ? number.format(Math.abs(signal.pct)) : undefined, qty: signal.qty != null ? number.format(signal.qty) : undefined, days: signal.days != null ? number.format(Math.round(signal.days)) : undefined, since: signal.since ? fmtDate(signal.since) : undefined };
    return t(`productHub.signals.${signal.kind}${signal.kind === 'restock' && signal.days == null ? 'NoCover' : ''}`, values);
  };

  return (
    <DashboardLayout>
      <BusinessPageContainer>
        {back}
        <div className="apex-page" dir={dir}>
          {notice && <Toast variant={notice.variant} message={notice.message} onClose={() => setNotice(null)} />}

          <Panel className="apex-panel--hero product-hero">
            <div className="product-hero__main">
              <div className="product-hero__identity">
                <span className="product-hero__avatar" aria-hidden="true">{(product.display_name || '?').trim().charAt(0)}</span>
                <div>
                  <p className="apex-eyebrow">{[product.display_category, product.display_brand].filter(Boolean).join(' · ') || t('productHub.uncategorised')}</p>
                  <h1 className="product-hero__title">{product.display_name}</h1>
                  <div className="product-hero__meta">
                    <span className="product-hero__price apex-num">{money(product.current_price, currency)}</span>
                    {product.margin_pct != null && <Pill tone={product.margin_pct >= 20 ? 'success' : product.margin_pct >= 0 ? 'warning' : 'danger'}>{t('productHub.margin', { pct: number.format(product.margin_pct) })}</Pill>}
                    {stock.current == null ? <Pill>{t('productHub.stockNotTracked')}</Pill> : <Pill tone={stock.current <= 0 ? 'danger' : stock.action === 'restock' ? 'warning' : 'success'}>{t('productHub.inStock', { qty: number.format(stock.current) })}</Pill>}
                  </div>
                </div>
              </div>
              <div className="product-hero__actions">
                <ApexButton icon={ShoppingCart} onClick={() => setSaleOpen(true)}>{t('productHub.actions.recordSale')}</ApexButton>
                <ApexButton variant="secondary" icon={Tag} onClick={() => setPriceOpen(true)}>{t('productHub.actions.priceAdvice')}</ApexButton>
                <ApexButton variant="secondary" icon={Megaphone} onClick={() => navigate(`${routePaths.marketing}?product=${product.product_id}`)}>{t('productHub.actions.promote')}</ApexButton>
                <ApexButton variant="ghost" icon={Pencil} onClick={() => navigate(routePaths.productEdit.replace(':productId', product.product_id))}>{t('productHub.actions.edit')}</ApexButton>
              </div>
            </div>
            {signals.length > 0 && (
              <ul className="product-signals" aria-label={t('productHub.signals.title')}>
                {signals.map((signal, index) => {
                  const Icon = TONE_ICON[signal.kind] || Sparkles;
                  return <li key={`${signal.kind}-${index}`} className={`product-signal product-signal--${signal.tone}`}><Icon size={15} aria-hidden="true" /><span>{signalText(signal)}</span></li>;
                })}
              </ul>
            )}
          </Panel>

          <div className="apex-grid apex-grid--stats">
            <Stat label={t('productHub.stats.units')} value={number.format(sales.units_last_30)} delta={sales.units_change_pct} deltaLabel={t('productHub.stats.vsPrev')} icon={ShoppingCart} />
            <Stat label={t('productHub.stats.revenue')} value={money(sales.revenue_last_30, sales.currency, 0)} delta={sales.revenue_change_pct} deltaLabel={t('productHub.stats.vsPrev')} icon={Coins} tone="violet" />
            <Stat
              label={t('productHub.stats.forecast')}
              value={demand.forecast_next_30 == null ? '—' : number.format(demand.forecast_next_30)}
              delta={demand.forecast_next_30 == null ? null : demand.trend_change_pct}
              deltaLabel={demand.forecast_next_30 == null ? null : t('productHub.stats.vsLast30')}
              hint={demand.forecast_next_30 == null ? (sales.last_sale_at ? t('productHub.stats.forecastPending') : t('productHub.stats.forecastNeedsSales')) : null}
              icon={CalendarRange}
              tone={demand.trend === 'decreasing' ? 'danger' : demand.trend === 'increasing' ? 'success' : 'accent'}
            />
            <Stat
              label={t('productHub.stats.cover')}
              value={stock.days_of_cover == null ? '—' : t('demandApex.table.days', { count: number.format(Math.round(stock.days_of_cover)) })}
              hint={stock.action && stock.action !== 'none' && demand.forecast_next_30 != null ? t(`demandApex.action.${stock.action}`) + (stock.suggested_qty ? ` · ${t(`demandApex.action.${stock.action}Qty`, { qty: number.format(stock.suggested_qty) })}` : '') : (stock.current == null ? t('productHub.stockNotTracked') : null)}
              icon={Boxes}
              tone={stock.action === 'restock' ? 'warning' : 'success'}
            />
          </div>

          <Panel eyebrow={t('productHub.demand.eyebrow')} title={t('productHub.demand.title')} subtitle={t('demandApex.chart.subtitle')}>
            {demand.series.some((p) => p.actual || p.forecast)
              ? <ForecastChart points={demand.series} locale={locale} todayDate={demand.as_of} height={260} labels={{ actual: t('demandApex.chart.actual'), forecast: t('demandApex.chart.forecast'), today: t('demandApex.chart.today') }} />
              : <StateBlock compact title={t('productHub.demand.emptyTitle')} description={t('productHub.demand.emptyDescription')} action={<ApexButton size="sm" icon={ShoppingCart} onClick={() => setSaleOpen(true)}>{t('productHub.actions.recordSale')}</ApexButton>} />}
          </Panel>

          <div className="apex-grid apex-grid--main-side">
            <Panel
              eyebrow={t('productHub.competition.eyebrow')}
              title={t('productHub.competition.title')}
              subtitle={t('productHub.competition.subtitle')}
              actions={<ApexButton size="sm" variant="secondary" onClick={() => navigate(routePaths.market)}>{t('productHub.competition.manage')}</ApexButton>}
              bodyClassName="is-flush"
            >
              {market && (
                <div className="product-market" style={{ padding: '0 22px 14px' }}>
                  <div className="product-market__row">
                    <span>{t('productHub.competition.lowest')} <strong className="apex-num">{money(market.lowest, currency)}</strong></span>
                    <span>{t('productHub.competition.average')} <strong className="apex-num">{money(market.average, currency)}</strong></span>
                    <span>{t('productHub.competition.highest')} <strong className="apex-num">{money(market.highest, currency)}</strong></span>
                    <span>{t('productHub.competition.yours')} <strong className="apex-num">{money(market.your_price, currency)}</strong></span>
                  </div>
                  <PricePosition market={market} label={t('productHub.competition.position')} />
                </div>
              )}
              {competitors.product_level.length === 0 ? (
                <StateBlock compact title={t('productHub.competition.noneTitle')} description={t('productHub.competition.noneDescription', { count: competitors.industry_level.length })} action={<ApexButton size="sm" onClick={() => navigate(`${routePaths.marketAddCompetitor}?product=${product.product_id}`)}>{t('productHub.competition.recordPrice')}</ApexButton>} />
              ) : (
                <div className="apex-table-wrap">
                  <table className="apex-table">
                    <thead><tr><th>{t('productHub.competition.competitor')}</th><th className="apex-table__num">{t('productHub.competition.price')}</th><th className="apex-table__num">{t('productHub.competition.vsYou')}</th><th className="apex-table__num">{t('productHub.competition.recorded')}</th></tr></thead>
                    <tbody>
                      {competitors.product_level.map((c) => (
                        <tr key={c.competitor_id}>
                          <td>
                            <button type="button" className="apex-table__link" onClick={() => navigate(routePaths.marketCompetitorDetail.replace(':competitorId', c.competitor_id))}>{c.name}</button>
                            <div><Pill tone={c.level === 'PRODUCT' ? 'violet' : 'neutral'}>{t(c.level === 'PRODUCT' ? 'productHub.competition.levelProduct' : 'productHub.competition.levelMarket')}</Pill></div>
                            {c.url && <a className="apex-inline-link" href={c.url} target="_blank" rel="noreferrer noopener" aria-label={t('productHub.competition.openListing', { name: c.name })}><ExternalLink size={12} /></a>}
                          </td>
                          <td className="apex-table__num apex-table__primary">{c.price == null ? '—' : money(c.price, c.currency)}{c.price_change_pct != null && <div><Delta value={c.price_change_pct} /></div>}</td>
                          <td className="apex-table__num">{c.vs_you_pct == null ? '—' : <Pill tone={c.vs_you_pct < 0 ? 'warning' : 'success'}>{t(c.vs_you_pct < 0 ? 'productHub.competition.cheaper' : c.vs_you_pct > 0 ? 'productHub.competition.pricier' : 'productHub.competition.same', { pct: number.format(Math.abs(c.vs_you_pct)) })}</Pill>}</td>
                          <td className="apex-table__num apex-muted">
                            {fmtDate(c.observed_at)}
                            <div className="product-price-source">
                              {c.source?.kind === 'product_page' && c.url
                                ? <a className="apex-inline-link" href={c.url} target="_blank" rel="noreferrer noopener">{t('productHub.competition.sourceProductPage')}</a>
                                : c.source?.kind === 'data_source'
                                  ? t('productHub.competition.sourceDataSource', { name: c.source.name })
                                  : t('productHub.competition.sourceManual')}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {competitors.industry_level.length > 0 && (
                <div className="product-industry">
                  <p className="apex-eyebrow">{t('productHub.competition.industryTitle')}</p>
                  <p className="apex-muted" style={{ fontSize: 12.5, margin: '4px 0 10px' }}>{t('productHub.competition.industryHint')}</p>
                  <div className="product-industry__chips">
                    {competitors.industry_level.map((c) => <button key={c.competitor_id} type="button" className="apex-chip" onClick={() => navigate(routePaths.marketCompetitorDetail.replace(':competitorId', c.competitor_id))}>{c.name}</button>)}
                  </div>
                </div>
              )}
            </Panel>

            <Panel eyebrow={t('productHub.reviews.eyebrow')} title={t('productHub.reviews.title')}>
              {reviews.count === 0 ? (
                <StateBlock compact title={t('productHub.reviews.emptyTitle')} description={t('productHub.reviews.emptyDescription')} action={<ApexButton size="sm" variant="secondary" onClick={() => navigate(routePaths.connectData)}>{t('productHub.reviews.import')}</ApexButton>} />
              ) : (
                <>
                  <div className="product-rating">
                    <strong className="apex-num">{reviews.average_rating != null ? number.format(reviews.average_rating) : '—'}</strong>
                    <span className="product-rating__stars" aria-hidden="true">{[1, 2, 3, 4, 5].map((n) => <Star key={n} size={15} fill={reviews.average_rating >= n - 0.25 ? 'currentColor' : 'none'} />)}</span>
                    <span className="apex-muted">{t('productHub.reviews.count', { count: reviews.count })}</span>
                  </div>
                  {reviews.analysed > 0 ? (
                    <div style={{ display: 'grid', gap: 6, margin: '12px 0' }}>
                      <span className="apex-muted" style={{ fontSize: 12.5 }}>{t('productHub.reviews.sentiment', { positive: reviews.positive, negative: reviews.negative, analysed: reviews.analysed })}</span>
                      <Meter value={reviews.positive} max={reviews.analysed} tone="success" label={t('productHub.reviews.positiveShare')} />
                      {reviews.sentiment_basis && reviews.sentiment_basis !== 'model' && <span className="apex-muted" style={{ fontSize: 11.5 }}>{t(reviews.sentiment_basis === 'star_rating' ? 'productHub.reviews.basisRatings' : 'productHub.reviews.basisMixed')}</span>}
                    </div>
                  ) : <p className="apex-muted" style={{ fontSize: 12.5 }}>{t('productHub.reviews.notAnalysed')}</p>}
                  <ul className="product-reviews">
                    {reviews.latest.map((review, index) => (
                      <li key={index}>
                        <div className="product-reviews__head"><span className="apex-num">{review.rating != null ? `★ ${number.format(review.rating)}` : ''}</span><span className="apex-muted">{fmtDate(review.date)}{review.platform ? ` · ${review.platform}` : ''}</span></div>
                        <p>{review.text}</p>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </Panel>
          </div>

          <Panel eyebrow={t('productHub.sales.eyebrow')} title={t('productHub.sales.title')} subtitle={sales.first_sale_at ? t('productHub.sales.subtitle', { units: number.format(sales.units_all_time), revenue: money(sales.revenue_all_time, sales.currency, 0), since: fmtDate(sales.first_sale_at) }) : null} bodyClassName="is-flush"
            actions={<ApexButton size="sm" variant="secondary" onClick={() => navigate(routePaths.reports)}>{t('productHub.sales.allSales')}</ApexButton>}>
            {sales.recent.length === 0 ? (
              <StateBlock compact title={t('productHub.sales.emptyTitle')} description={t('productHub.sales.emptyDescription')} action={<ApexButton size="sm" icon={ShoppingCart} onClick={() => setSaleOpen(true)}>{t('productHub.actions.recordSale')}</ApexButton>} />
            ) : (
              <div className="apex-table-wrap">
                <table className="apex-table">
                  <thead><tr><th>{t('productHub.sales.date')}</th><th className="apex-table__num">{t('productHub.sales.quantity')}</th><th className="apex-table__num">{t('productHub.sales.unitPrice')}</th><th className="apex-table__num">{t('productHub.sales.total')}</th></tr></thead>
                  <tbody>{sales.recent.map((sale, index) => <tr key={index}><td>{fmtDate(sale.date)}</td><td className="apex-table__num">{number.format(sale.quantity)}</td><td className="apex-table__num">{money(sale.unit_price, sale.currency)}</td><td className="apex-table__num apex-table__primary">{money(sale.total, sale.currency)}</td></tr>)}</tbody>
                </table>
              </div>
            )}
          </Panel>
          <p className="apex-source">{t('productHub.sources')}</p>
        </div>

        <QuickSaleModal open={saleOpen} product={listProduct} onClose={() => setSaleOpen(false)} currencyFormatter={currencyFormatter} t={t} onNotice={(variant, message) => setNotice({ variant, message })} />
        <PriceRecommendationModal open={priceOpen} product={listProduct} onClose={() => setPriceOpen(false)} currencyFormatter={currencyFormatter} t={t} />
      </BusinessPageContainer>
    </DashboardLayout>
  );
}

function PricePosition({ market, label }) {
  const span = market.highest - market.lowest;
  const clamp = (v) => Math.max(0, Math.min(100, v));
  const at = span > 0 ? clamp(((market.your_price - market.lowest) / span) * 100) : 50;
  return (
    <div className="price-position" role="img" aria-label={label}>
      <div className="price-position__track"><span className="price-position__you" style={{ insetInlineStart: `${at}%` }} /></div>
    </div>
  );
}

export default ProductHubPage;
