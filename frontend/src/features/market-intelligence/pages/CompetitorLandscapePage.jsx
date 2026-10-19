import { MarketTabs } from '../components/MarketTabs.jsx';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Layers, MapPin, Package, Plus, RefreshCw, Search, ShieldCheck, Tag, Users } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { DashboardLayout } from '../../../app/layouts/DashboardLayout.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import BusinessPageContainer from '../../../shared/components/layout/BusinessPageContainer.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import { ApexButton, Meter, Panel, Pill, Stat, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import { competitorsApi } from '../api/competitorsApi.js';
import { MarketScan } from '../components/MarketScan.jsx';
import { MarketInsights } from '../components/MarketInsights.jsx';
import { CompetitorDirectory } from '../components/CompetitorDirectory.jsx';
import { PriceCoverage } from '../components/PriceCoverage.jsx';
import { useRetryAllFailed } from '../hooks/useCompetitorData.js';
import { retryOutcome } from '../api/competitorDataApi.js';

const COVERAGE_FILTERS = ['all', 'none', 'above'];

export function CompetitorLandscapePage() {
  const { t, locale, dir } = useI18n();
  const navigate = useNavigate();
  const [coverageFilter, setCoverageFilter] = useState('all');
  const [search, setSearch] = useState('');
  const query = useQuery({ queryKey: ['competitor-landscape'], queryFn: competitorsApi.landscape });
  const retryAll = useRetryAllFailed();

  const number = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  const money = (amount, currency) => (amount == null || !currency ? '—' : new Intl.NumberFormat(locale, { style: 'currency', currency }).format(amount));
  const productPath = (id) => routePaths.productDetail.replace(':productId', id);

  const header = (
    <PageHeader
      title={t('competitorsApex.title')}
      subtitle={t('competitorsApex.subtitle')}
      actions={(
        <>
          <ApexButton variant="ghost" icon={RefreshCw} loading={retryAll.isPending} title={t('competitorData.retryAllHint')} onClick={() => retryAll.mutate()}>{t('competitorData.retryAll')}</ApexButton>
          <ApexButton variant="ghost" icon={MapPin} onClick={() => navigate(routePaths.marketSearchScope)}>{t('competitorsApex.searchArea')}</ApexButton>
          <ApexButton variant="secondary" icon={ShieldCheck} onClick={() => navigate(routePaths.marketPendingSources)}>{t('competitorsApex.sources')}</ApexButton>
          <ApexButton icon={Plus} onClick={() => navigate(routePaths.marketAddCompetitor)}>{t('competitorsApex.add.button')}</ApexButton>
        </>
      )}
    />
  );

  if (query.isPending) return <DashboardLayout><BusinessPageContainer>{header}<Panel><StateBlock kind="loading" title={t('common.loading')} /></Panel></BusinessPageContainer></DashboardLayout>;
  if (query.isError) return <DashboardLayout><BusinessPageContainer>{header}<Panel><StateBlock kind="error" title={t('competitorsApex.error')} onRetry={() => query.refetch()} retryLabel={t('demandApex.actions.retry')} /></Panel></BusinessPageContainer></DashboardLayout>;

  const data = query.data;
  const pricing = Object.fromEntries(data.competitors.map((c) => [c.competitor_id, c]));
  const needle = search.trim().toLowerCase();
  const coverage = data.products.filter((p) => (!needle || p.name.toLowerCase().includes(needle))
    && (coverageFilter === 'all' || (coverageFilter === 'none' ? p.competitor_count === 0 : (p.gap_pct ?? 0) >= 5)));
  const limit = data.plan_limit;

  return (
    <DashboardLayout>
      <BusinessPageContainer>
        {header}
        <MarketTabs />
        <div className="apex-page" dir={dir}>
          <p className="price-coverage__note apex-muted" role="status" aria-live="polite">
            {retryAll.isError ? t('competitorData.outcome.error') : retryAll.data ? t(`competitorData.outcome.${retryOutcome(retryAll.data)}`) : ''}
          </p>
          <div className="apex-grid apex-grid--stats">
            <Stat label={t('competitorsApex.stats.tracked')} value={number.format(data.competitors.length)} hint={limit != null ? t('competitorsApex.stats.ofPlan', { limit: number.format(limit) }) : t('competitorsApex.stats.unlimited')} icon={Users} />
            <Stat label={t('competitorsApex.stats.levels')} value={`${number.format(data.market_wide)} · ${number.format(data.product_level)}`} hint={t('competitorsApex.stats.levelsHint')} icon={Layers} tone="violet" />
            <Stat label={t('competitorsApex.stats.coverage')} value={`${number.format(data.products_covered)} / ${number.format(data.catalog_size)}`} hint={t('competitorsApex.stats.coverageHint')} icon={Package} tone={data.products_covered < data.catalog_size ? 'warning' : 'success'} />
            <Stat label={t('competitorsApex.stats.above')} value={number.format(data.products_priced_above)} hint={t('competitorsApex.stats.changes', { count: number.format(data.price_changes_30d) })} icon={Tag} tone="danger" />
          </div>
          {limit != null && <div className="apex-limit-bar"><span>{t('competitorsApex.stats.planUsage', { used: data.competitors.length, limit })}</span><Meter value={data.competitors.length} max={limit} tone={data.competitors.length >= limit ? 'danger' : 'accent'} label={t('competitorsApex.stats.tracked')} /></div>}

          <MarketScan />
          <CompetitorDirectory pricing={pricing} planLimit={limit} />
          <PriceCoverage />
          <MarketInsights />

          <Panel
            eyebrow={t('competitorsApex.coverage.eyebrow')}
            title={t('competitorsApex.coverage.title')}
            subtitle={t('competitorsApex.coverage.subtitle')}
            bodyClassName="is-flush"
            actions={(
              <>
                <label className="apex-search"><Search size={15} aria-hidden="true" /><input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t('products.list.searchPlaceholder')} aria-label={t('products.list.searchPlaceholder')} /></label>
                <div className="apex-segmented" role="group" aria-label={t('competitorsApex.coverage.filter')}>{COVERAGE_FILTERS.map((key) => <button key={key} type="button" aria-pressed={coverageFilter === key} onClick={() => setCoverageFilter(key)}>{t(`competitorsApex.coverage.filters.${key}`)}</button>)}</div>
              </>
            )}
          >
            {coverage.length === 0 ? <StateBlock compact title={t('demandApex.table.noMatch')} /> : (
              <div className="apex-table-wrap">
                <table className="apex-table">
                  <thead><tr>
                    <th>{t('competitorsApex.coverage.product')}</th>
                    <th className="apex-table__num">{t('competitorsApex.coverage.yours')}</th>
                    <th className="apex-table__num">{t('competitorsApex.coverage.competitors')}</th>
                    <th>{t('competitorsApex.coverage.cheapest')}</th>
                    <th className="apex-table__num">{t('competitorsApex.coverage.average')}</th>
                    <th className="apex-table__num">{t('competitorsApex.coverage.position')}</th>
                  </tr></thead>
                  <tbody>
                    {coverage.map((p) => (
                      <tr key={p.product_id}>
                        <td><button type="button" className="apex-table__link" onClick={() => navigate(productPath(p.product_id))}>{p.name}</button>{p.category && <div className="apex-muted products-apex-sub">{p.category}</div>}</td>
                        <td className="apex-table__num apex-table__primary">{money(p.your_price, p.currency)}</td>
                        <td className="apex-table__num">{p.competitor_count || <span className="apex-muted">0</span>}</td>
                        <td>{p.cheapest ? <span><strong className="apex-num">{money(p.cheapest.price, p.currency)}</strong> <span className="apex-muted">· {p.cheapest.name}</span></span> : (
                          <button type="button" className="apex-chip" onClick={() => navigate(`${routePaths.marketAddCompetitor}?product=${p.product_id}`)}>{t('competitorsApex.coverage.addFor')}</button>
                        )}</td>
                        <td className="apex-table__num">{money(p.market_average, p.currency)}</td>
                        <td className="apex-table__num">{p.gap_pct == null ? '—' : <Pill tone={Math.abs(p.gap_pct) < 5 ? 'neutral' : p.gap_pct > 0 ? 'warning' : 'success'}>{p.gap_pct > 0 ? '+' : ''}{number.format(p.gap_pct)}%</Pill>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
          <p className="apex-source">{t('competitorsApex.sourcesNote')}</p>
        </div>
      </BusinessPageContainer>
    </DashboardLayout>
  );
}

export default CompetitorLandscapePage;
