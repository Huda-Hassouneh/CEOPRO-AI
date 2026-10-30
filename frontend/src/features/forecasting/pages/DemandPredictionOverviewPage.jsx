import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, Boxes, CalendarRange, Coins, RefreshCw, TrendingDown, TrendingUp, Upload, Info } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import BusinessPageContainer from '../../../shared/components/layout/BusinessPageContainer.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import { ApexButton, Delta, Meter, Pager, Panel, Pill, Stat, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import ForecastChart from '../../../shared/components/charts/ForecastChart.jsx';
import { useDemandForecastHistory, useDemandOverview, useGenerateForecast, useRefreshForecasts } from '../hooks/useDemandOverview.js';

const TREND_TONE = { increasing: 'success', decreasing: 'danger', stable: 'neutral', not_forecast: 'neutral', no_sales: 'neutral' };
const ACTION_TONE = { restock: 'warning', reduce: 'violet', monitor: 'neutral', none: 'neutral' };
const FILTERS = ['all', 'increasing', 'decreasing', 'restock'];
const PAGE_SIZE = 50;

export function DemandPredictionOverviewPage() {
  const { t, locale, dir } = useI18n();
  const navigate = useNavigate();
  const [productId, setProductId] = useState('all');
  const [filter, setFilter] = useState('all');
  const [sort, setSort] = useState({ key: 'forecast_next_30', desc: true });
  const query = useDemandOverview({ productId });
  const refresh = useRefreshForecasts();
  const generate = useGenerateForecast();
  const history = useDemandForecastHistory(productId);
  const data = query.data;

  const number = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  const money = (amount, currency) => (amount == null || !currency ? '—' : new Intl.NumberFormat(locale, { style: 'currency', currency, maximumFractionDigits: 0 }).format(amount));
  const units = (value) => (value == null ? '—' : number.format(value));

  const rows = useMemo(() => {
    const products = data?.products ?? [];
    const visible = products.filter((p) => (productId === 'all' || p.product_id === productId) && (
      filter === 'all' ? true : filter === 'restock' ? p.stock_action === 'restock' : p.trend === filter));
    const value = (p) => p[sort.key] ?? (sort.desc ? -Infinity : Infinity);
    return [...visible].sort((a, b) => {
      const av = value(a);
      const bv = value(b);
      if (typeof av === 'string') return sort.desc ? String(bv).localeCompare(av, locale) : String(av).localeCompare(String(bv), locale);
      return sort.desc ? bv - av : av - bv;
    });
  }, [data, productId, filter, sort, locale]);

  // The overview carries every product (the totals need them all); the
  // table shows them a page at a time.
  const [page, setPage] = useState(0);
  useEffect(() => setPage(0), [productId, filter, sort]);
  const pageRows = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const sortBy = (key) => setSort((current) => ({ key, desc: current.key === key ? !current.desc : key !== 'name' }));
  const sortState = (key) => (sort.key === key ? (sort.desc ? 'descending' : 'ascending') : 'none');

  const header = (
    <PageHeader
      title={t('demandApex.title')}
      subtitle={t('demandApex.subtitle')}
      actions={data?.products?.length ? (
        <>
          <label className="apex-field demand-product-filter">
            <span className="sr-only">{t('demandApex.filters.product')}</span>
            <select className="apex-select" value={productId} onChange={(event) => setProductId(event.target.value)} aria-label={t('demandApex.filters.product')}>
              <option value="all">{t('demandApex.filters.allProducts')}</option>
              {data.products.map((p) => <option key={p.product_id} value={p.product_id}>{p.name}</option>)}
            </select>
          </label>
          {productId === 'all' ? (
            <ApexButton variant="secondary" icon={RefreshCw} loading={refresh.isPending} disabled={data?.refresh?.state === 'running'} onClick={() => refresh.mutate()}>
              {t('demandApex.actions.refresh')}
            </ApexButton>
          ) : (
            <ApexButton variant="secondary" icon={RefreshCw} loading={generate.isPending} onClick={() => generate.mutate(productId)}>
              {t('demandApex.actions.generateSelected')}
            </ApexButton>
          )}
        </>
      ) : null}
    />
  );

  if (query.isPending) {
    return <BusinessPageContainer>{header}<div className="apex-page"><div className="apex-grid apex-grid--stats">{[0, 1, 2, 3].map((i) => <Panel key={i}><StateBlock kind="loading" compact title={t('common.loading')} /></Panel>)}</div><Panel><StateBlock kind="loading" title={t('common.loading')} /></Panel></div></BusinessPageContainer>;
  }

  if (query.isError) {
    return <BusinessPageContainer>{header}<Panel><StateBlock kind="error" title={t('demandApex.error.title')} description={t('demandApex.error.description')} onRetry={() => query.refetch()} retryLabel={t('demandApex.actions.retry')} /></Panel></BusinessPageContainer>;
  }

  const totals = data.totals;
  const refreshing = data.refresh?.state === 'running';
  const allProducts = data.products;
  const noProducts = allProducts.length === 0;
  const noSales = !noProducts && allProducts.every((p) => !p.last_sale_at);
  const today = data.as_of;

  if (noProducts || noSales) {
    return (
      <BusinessPageContainer>
        {header}
        <Panel>
          <StateBlock
            kind="empty"
            title={noProducts ? t('demandApex.empty.noProductsTitle') : t('demandApex.empty.noSalesTitle')}
            description={noProducts ? t('demandApex.empty.noProductsDescription') : t('demandApex.empty.noSalesDescription')}
            action={noProducts
              ? <ApexButton onClick={() => navigate(routePaths.productNew)}>{t('demandApex.actions.addProduct')}</ApexButton>
              : <><ApexButton icon={Upload} onClick={() => navigate(routePaths.connectData)}>{t('demandApex.actions.importSales')}</ApexButton><ApexButton variant="secondary" onClick={() => navigate(routePaths.products)}>{t('demandApex.actions.recordSale')}</ApexButton></>}
          />
        </Panel>
      </BusinessPageContainer>
    );
  }

  const progress = data.refresh;
  return (
    <BusinessPageContainer>
      {header}
      <div className="apex-page" dir={dir}>
        {(refreshing || refresh.isError || progress?.state === 'failed' || progress?.state === 'blocked' || generate.isError || generate.data?.status === 'UNKNOWN') && (
          <div className={`apex-notice ${refresh.isError || progress?.state === 'failed' || progress?.state === 'blocked' ? 'apex-notice--danger' : 'apex-notice--info'}`} role="status" aria-live="polite">
            {refresh.isError || progress?.state === 'failed' || progress?.state === 'blocked' || generate.isError ? <AlertTriangle size={16} /> : <RefreshCw size={16} className={refreshing || generate.isPending ? 'apex-rotating' : undefined} />}
            <div style={{ flex: 1 }}>
              <strong>{progress?.state === 'blocked' ? t('demandApex.refresh.blocked') : generate.data?.status === 'UNKNOWN' ? t('demandApex.refresh.noHistory') : refresh.isError || progress?.state === 'failed' || generate.isError ? t('demandApex.refresh.failed') : generate.isPending ? t('demandApex.refresh.generating') : t('demandApex.refresh.running', { done: progress?.done ?? 0, total: progress?.total ?? progress?.pending_products ?? '…' })}</strong>
              {refreshing && progress?.total ? <div style={{ marginTop: 8 }}><Meter value={progress.done ?? 0} max={progress.total} label={t('demandApex.refresh.label')} /></div> : null}
            </div>
          </div>
        )}

        <div className="apex-grid apex-grid--stats">
          <Stat
            label={t('demandApex.stats.forecast')}
            value={totals.forecasted ? units(totals.forecast_next_30) : '—'}
            delta={totals.change_pct}
            deltaLabel={t('demandApex.stats.vsLast30')}
            hint={totals.forecasted ? null : t('demandApex.stats.calculating')}
            icon={CalendarRange}
          />
          <Stat label={t('demandApex.stats.revenue')} value={money(totals.expected_revenue, totals.currency)} hint={t('demandApex.stats.revenueHint')} icon={Coins} tone="violet" />
          <Stat label={t('demandApex.stats.rising')} value={number.format(totals.increasing)} hint={t('demandApex.stats.ofForecasted', { count: totals.forecasted })} icon={TrendingUp} tone="success" />
          <Stat label={t('demandApex.stats.falling')} value={number.format(totals.decreasing)} hint={t('demandApex.stats.stable', { count: totals.stable })} icon={TrendingDown} tone="danger" />
          <Stat label={t('demandApex.stats.restock')} value={number.format(totals.restock)} hint={t('demandApex.stats.restockHint')} icon={Boxes} tone="warning" />
        </div>

        <Panel
          eyebrow={t('demandApex.chart.eyebrow')}
          title={productId === 'all' ? t('demandApex.chart.titleAll') : t('demandApex.chart.titleOne', { name: allProducts.find((p) => p.product_id === productId)?.name ?? '' })}
          subtitle={t('demandApex.chart.subtitle')}
        >
          {data.series.some((p) => p.actual || p.forecast) ? (
            <ForecastChart points={data.series} locale={locale} todayDate={today} labels={{ actual: t('demandApex.chart.actual'), forecast: t('demandApex.chart.forecast'), today: t('demandApex.chart.today') }} />
          ) : (
            <StateBlock compact title={t('demandApex.chart.emptyTitle')} description={t('demandApex.chart.emptyDescription')} />
          )}
        </Panel>

        {productId !== 'all' && (
          <Panel eyebrow={t('demandApex.history.eyebrow')} title={t('demandApex.history.title')} subtitle={t('demandApex.history.subtitle')}>
            {history.isPending ? <StateBlock kind="loading" compact title={t('common.loading')} />
              : history.isError ? <StateBlock kind="error" compact title={t('demandApex.history.error')} onRetry={() => history.refetch()} retryLabel={t('demandApex.actions.retry')} />
                : history.data.forecast_history.length === 0 ? <StateBlock kind="empty" compact title={t('demandApex.history.empty')} description={t('demandApex.history.emptyDescription')} />
                  : <div className="apex-table-wrap"><table className="apex-table"><thead><tr><th>{t('demandApex.history.generated')}</th><th>{t('demandApex.history.target')}</th><th className="apex-table__num">{t('demandApex.table.forecast')}</th><th className="apex-table__num">{t('demandApex.history.range')}</th><th className="apex-table__num">{t('demandApex.history.confidence')}</th></tr></thead><tbody>{history.data.forecast_history.map((run, index) => <tr key={`${run.created_at}-${index}`}><td>{new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(run.created_at))}</td><td>{new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(new Date(run.forecast_target_date))}</td><td className="apex-table__num">{units(run.predicted_demand)}</td><td className="apex-table__num">{run.confidence_range_lower == null || run.confidence_range_upper == null ? '—' : `${units(run.confidence_range_lower)}–${units(run.confidence_range_upper)}`}</td><td className="apex-table__num">{run.confidence_score == null ? '—' : `${number.format(run.confidence_score * 100)}%`}</td></tr>)}</tbody></table></div>}
          </Panel>
        )}

        <Panel
          eyebrow={t('demandApex.table.eyebrow')}
          title={t('demandApex.table.title')}
          subtitle={t('demandApex.table.subtitle', { band: data.trend_band_pct })}
          actions={(
            <div className="apex-segmented" role="group" aria-label={t('demandApex.filters.label')}>
              {FILTERS.map((key) => <button key={key} type="button" aria-pressed={filter === key} onClick={() => setFilter(key)}>{t(`demandApex.filters.${key}`)}</button>)}
            </div>
          )}
          bodyClassName="is-flush"
        >
          {rows.length === 0 ? (
            <StateBlock compact title={t('demandApex.table.noMatch')} />
          ) : (
            <div className="apex-table-wrap">
              <table className="apex-table">
                <thead>
                  <tr>
                    <th aria-sort={sortState('name')}><button type="button" className="demand-sort" onClick={() => sortBy('name')}>{t('demandApex.table.product')}</button></th>
                    <th className="apex-table__num" aria-sort={sortState('sold_last_30')}><button type="button" className="demand-sort" onClick={() => sortBy('sold_last_30')}>{t('demandApex.table.sold')}</button></th>
                    <th className="apex-table__num" aria-sort={sortState('forecast_next_30')}><button type="button" className="demand-sort" onClick={() => sortBy('forecast_next_30')}>{t('demandApex.table.forecast')}</button></th>
                    <th aria-sort={sortState('trend_change_pct')}><button type="button" className="demand-sort" onClick={() => sortBy('trend_change_pct')}>{t('demandApex.table.trend')}</button></th>
                    <th className="apex-table__num" aria-sort={sortState('current_stock')}><button type="button" className="demand-sort" onClick={() => sortBy('current_stock')}>{t('demandApex.table.stock')}</button></th>
                    <th className="apex-table__num" aria-sort={sortState('stock_days_of_cover')}><button type="button" className="demand-sort" onClick={() => sortBy('stock_days_of_cover')}>{t('demandApex.table.cover')}</button></th>
                    <th>{t('demandApex.table.advice')}</th>
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((p) => (
                    <tr key={p.product_id}>
                      <td>
                        <button type="button" className="apex-table__link" onClick={() => navigate(`/products/${p.product_id}`)}>{p.name}</button>
                        {p.category && <div className="apex-muted" style={{ fontSize: 12, marginTop: 2 }}>{p.category}</div>}
                      </td>
                      <td className="apex-table__num">{units(p.sold_last_30)}</td>
                      <td className="apex-table__num apex-table__primary">
                        {p.forecast_next_30 == null ? <span className="apex-muted">{refreshing ? t('demandApex.table.calculating') : t('demandApex.table.noForecast')}</span> : units(p.forecast_next_30)}
                        {p.forecast_lower != null && p.forecast_upper != null && <div className="apex-muted" style={{ fontSize: 11.5, fontWeight: 500 }} dir="ltr">{units(p.forecast_lower)}–{units(p.forecast_upper)}</div>}
                        {p.forecast_next_30 != null && p.data_sufficiency?.sufficient === false && <div className="apex-muted" style={{ fontSize: 11.5 }}>{t('demandApex.history.buildingData', { days: p.data_sufficiency.available_days, minimum: p.data_sufficiency.minimum_required })}</div>}
                      </td>
                      <td>
                        {p.forecast_next_30 == null ? <span className="apex-muted">—</span> : (
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                            <Pill tone={TREND_TONE[p.trend]}>{t(`demandApex.trend.${p.trend}`)}</Pill>
                            {p.trend_change_pct != null && <Delta value={p.trend_change_pct} />}
                          </span>
                        )}
                      </td>
                      <td className="apex-table__num">{p.current_stock == null ? <span className="apex-muted">{t('demandApex.table.notTracked')}</span> : units(p.current_stock)}</td>
                      <td className="apex-table__num">{p.stock_days_of_cover == null ? '—' : t('demandApex.table.days', { count: number.format(Math.round(p.stock_days_of_cover)) })}</td>
                      <td>
                        {p.stock_action && p.stock_action !== 'none' && p.forecast_next_30 != null ? (
                          <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 4 }}>
                            <Pill tone={ACTION_TONE[p.stock_action]} icon={p.stock_priority === 'high' ? AlertTriangle : undefined}>{t(`demandApex.action.${p.stock_action}`)}</Pill>
                            {p.stock_suggested_qty > 0 && <span className="apex-muted" style={{ fontSize: 12 }}>{t(`demandApex.action.${p.stock_action}Qty`, { qty: number.format(p.stock_suggested_qty) })}</span>}
                          </span>
                        ) : <span className="apex-muted">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Pager page={page} pageSize={PAGE_SIZE} total={rows.length} onChange={setPage} t={t} dir={dir} number={number} />
            </div>
          )}
          <p className="apex-source" style={{ padding: '0 22px 18px' }}><Info size={13} aria-hidden="true" />{t('demandApex.method')}</p>
        </Panel>
      </div>
    </BusinessPageContainer>
  );
}

export default DemandPredictionOverviewPage;
