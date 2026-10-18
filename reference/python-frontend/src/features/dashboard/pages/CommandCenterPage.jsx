import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowRight, BarChart3, Boxes, BrainCircuit, CalendarRange, Coins, Megaphone, Package, ShoppingCart,
  Tag, TrendingDown, TrendingUp, Upload, Users, FileText, CheckCircle2,
} from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useAuthStore } from '../../auth/store/authStore.js';
import BusinessPageContainer from '../../../shared/components/layout/BusinessPageContainer.jsx';
import { ApexButton, Delta, Panel, Pill, Stat, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import TrendChart from '../../../shared/components/charts/TrendChart.jsx';
import httpClient from '../../../shared/lib/httpClient.js';
import '../styles/CommandCenter.css';
import { DashboardActivity } from '../components/DashboardActivity.jsx';

const WINDOWS = [7, 30, 90];

const ACTION_ICON = { restock: Boxes, declining: TrendingDown, priced_above: Tag, promote_rising: Megaphone, promote_overstock: Megaphone, promote_growing: Megaphone };
const ACTION_TONE = { high: 'danger', medium: 'warning', low: 'accent' };

export function CommandCenterPage() {
  const { t, locale, dir } = useI18n();
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const [windowDays, setWindowDays] = useState(30);
  const query = useQuery({
    queryKey: ['dashboard', 'command-center', windowDays],
    queryFn: async () => (await httpClient.get('/dashboard/command-center', { params: { window_days: windowDays } })).data,
    placeholderData: (previous) => previous,
  });

  const number = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  const money = (amount, currency, digits = 0) => (amount == null || !currency ? '—' : new Intl.NumberFormat(locale, { style: 'currency', currency, maximumFractionDigits: digits }).format(amount));
  const productPath = (id) => routePaths.productDetail.replace(':productId', id);
  const fullName = (user?.displayName || user?.fullName || user?.name || user?.profile?.fullName || user?.email || '').trim();
  const initials = fullName.split(/[\s@.]+/u).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toLocaleUpperCase() || '·';
  const firstName = (user?.displayName || user?.fullName || user?.name || user?.profile?.fullName || '').trim().split(/\s+/u)[0] || '';
  const hour = new Date().getHours();
  const greeting = t(hour < 12 ? 'commandCenter.greeting.morning' : hour < 18 ? 'commandCenter.greeting.afternoon' : 'commandCenter.greeting.evening', { name: firstName });
  const today = new Intl.DateTimeFormat(locale, { weekday: 'long', day: 'numeric', month: 'long' }).format(new Date());

  if (query.isPending) {
    return <BusinessPageContainer><div className="apex-page cc-page"><Panel className="apex-panel--hero"><StateBlock kind="loading" title={t('common.loading')} /></Panel><div className="apex-grid apex-grid--stats">{[0, 1, 2, 3].map((i) => <Panel key={i}><StateBlock kind="loading" compact /></Panel>)}</div></div></BusinessPageContainer>;
  }
  if (query.isError) {
    return <BusinessPageContainer><Panel><StateBlock kind="error" title={t('commandCenter.error.title')} description={t('commandCenter.error.description')} onRetry={() => query.refetch()} retryLabel={t('demandApex.actions.retry')} /></Panel></BusinessPageContainer>;
  }

  const data = query.data;
  const m = data.metrics;
  const currency = m.revenue.currency || data.today.currency;

  if (!data.has_sales) {
    const steps = [
      { done: data.product_count > 0, icon: Package, key: 'products', to: routePaths.products },
      { done: false, icon: Upload, key: 'sales', to: routePaths.connectData },
      { done: m.competitors_tracked.count > 0, icon: Users, key: 'competitors', to: routePaths.marketCompetitors },
      { done: false, icon: FileText, key: 'documents', to: routePaths.aiAdvisor },
    ];
    return (
      <BusinessPageContainer>
        <div className="apex-page cc-page" dir={dir}>
          <Panel className="apex-panel--hero" eyebrow={today} title={greeting} subtitle={t('commandCenter.setup.subtitle')}>
            <ol className="cc-setup">
              {steps.map((step, index) => {
                const Icon = step.done ? CheckCircle2 : step.icon;
                return (
                  <li key={step.key} className={step.done ? 'is-done' : ''}>
                    <span className="cc-setup__icon" aria-hidden="true"><Icon size={18} /></span>
                    <div><strong>{index + 1}. {t(`commandCenter.setup.${step.key}.title`)}</strong><p>{t(`commandCenter.setup.${step.key}.description`)}</p></div>
                    {!step.done && <ApexButton size="sm" variant={index === 1 ? 'primary' : 'secondary'} onClick={() => navigate(step.to)}>{t(`commandCenter.setup.${step.key}.action`)}</ApexButton>}
                  </li>
                );
              })}
            </ol>
          </Panel>
          <DashboardActivity />
        </div>
      </BusinessPageContainer>
    );
  }

  const actionText = (action) => t(`commandCenter.actions.${action.kind}`, {
    name: action.name,
    qty: action.suggested_qty != null ? number.format(action.suggested_qty) : '',
    days: action.days_of_cover != null ? number.format(Math.round(action.days_of_cover)) : action.days != null ? number.format(Math.round(action.days)) : '',
    pct: action.pct != null ? number.format(Math.abs(action.pct)) : '',
    competitor: action.competitor,
  });

  return (
    <BusinessPageContainer>
      <div className="apex-page cc-page" dir={dir}>
        <Panel className="apex-panel--hero cc-hero">
          <div className="cc-hero__row">
            <div className="cc-hero__identity">
              <span className="gl-orb" aria-hidden="true"><span>{initials}</span></span>
              <div>
              <p className="apex-eyebrow">{today}</p>
              <h1 className="cc-hero__title">{greeting}</h1>
              <p className="cc-hero__summary">{t('commandCenter.summary', {
                revenue: money(m.revenue.amount, currency),
                days: windowDays,
                attention: number.format(data.actions.filter((a) => a.priority !== 'low').length),
              })}</p>
              </div>
            </div>
            <div className="cc-today">
              <span className="apex-muted">{t('commandCenter.today.label')}</span>
              <strong className="apex-num">{money(data.today.revenue, data.today.currency || currency)}</strong>
              <span className="apex-muted">{t('commandCenter.today.orders', { count: number.format(data.today.orders) })}</span>
            </div>
          </div>
          <div className="cc-hero__controls">
            <div className="apex-segmented" role="group" aria-label={t('commandCenter.window.label')}>
              {WINDOWS.map((days) => <button key={days} type="button" aria-pressed={windowDays === days} onClick={() => setWindowDays(days)}>{t('commandCenter.window.days', { count: days })}</button>)}
            </div>
            <ApexButton variant="secondary" icon={BrainCircuit} onClick={() => navigate(routePaths.aiAdvisor)}>{t('commandCenter.askAssistant')}</ApexButton>
          </div>
        </Panel>

        <div className="apex-grid apex-grid--stats">
          <Stat label={t('commandCenter.kpi.revenue', { days: windowDays })} value={money(m.revenue.amount, currency)} delta={m.revenue.change_pct} deltaLabel={t('commandCenter.kpi.vsPrev')} hint={m.revenue.change_pct == null ? t('commandCenter.kpi.noPrev') : null} icon={Coins} />
          <Stat label={t('commandCenter.kpi.units', { days: windowDays })} value={number.format(m.units_sold.units)} delta={m.units_sold.change_pct} deltaLabel={t('commandCenter.kpi.vsPrev')} icon={ShoppingCart} tone="violet" />
          <Stat label={t('commandCenter.kpi.forecast')} value={data.demand.forecasted ? number.format(data.demand.forecast_next_30) : '—'} delta={data.demand.change_pct} deltaLabel={t('demandApex.stats.vsLast30')} hint={data.demand.forecasted ? null : t('demandApex.stats.calculating')} icon={CalendarRange} tone="success" />
          <Stat label={t('commandCenter.kpi.restock')} value={number.format(data.restock_total)} hint={t('commandCenter.kpi.restockHint')} icon={Boxes} tone={data.restock_total ? 'warning' : 'success'} />
          <Stat label={t('commandCenter.kpi.competitors')} value={number.format(m.competitors_tracked.count)} hint={m.competitors_tracked.new_this_window ? t('commandCenter.kpi.newCompetitors', { count: m.competitors_tracked.new_this_window }) : null} icon={Users} />
        </div>

        <div className="apex-grid apex-grid--main-side">
          <Panel eyebrow={t('commandCenter.trend.eyebrow')} title={t('commandCenter.trend.title', { days: windowDays })} actions={<ApexButton size="sm" variant="ghost" onClick={() => navigate(routePaths.reports)}>{t('commandCenter.trend.reports')}<ArrowRight size={14} className="apex-flip-rtl" /></ApexButton>}>
            {data.sales_trend?.points?.length
              ? <TrendChart points={data.sales_trend.points} locale={locale} formatValue={(v) => money(v, currency, 2)} valueLabel={t('commandCenter.trend.revenue')} />
              : <StateBlock compact title={t('commandCenter.trend.empty')} />}
          </Panel>
          <Panel eyebrow={t('commandCenter.next.eyebrow')} title={t('commandCenter.next.title')}>
            {data.actions.length === 0 ? (
              <StateBlock compact title={t('commandCenter.next.allClear')} description={t('commandCenter.next.allClearHint')} />
            ) : (
              <ul className="cc-actions">
                {data.actions.map((action, index) => {
                  const Icon = ACTION_ICON[action.kind] || ArrowRight;
                  const promote = action.kind.startsWith('promote');
                  return (
                    <li key={`${action.kind}-${action.product_id}-${index}`}>
                      <span className={`cc-actions__icon is-${ACTION_TONE[action.priority] || 'accent'}`} aria-hidden="true"><Icon size={16} /></span>
                      <p>{actionText(action)}</p>
                      <button type="button" className="cc-actions__go" onClick={() => navigate(promote ? `${routePaths.marketing}?product=${action.product_id}` : productPath(action.product_id))} aria-label={t('commandCenter.next.open', { name: action.name })}>
                        {promote ? t('commandCenter.next.promote') : t('commandCenter.next.view')}<ArrowRight size={13} className="apex-flip-rtl" />
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>
        </div>

        <DashboardActivity />

        <div className="apex-grid apex-grid--3">
          <ProductList title={t('commandCenter.lists.top')} icon={TrendingUp} rows={data.top_products} empty={t('commandCenter.lists.empty')} onOpen={(id) => navigate(productPath(id))}
            render={(p) => <><span className="apex-num">{money(p.revenue, p.currency)}</span><Delta value={p.revenue_change_pct} /></>} />
          <ProductList title={t('commandCenter.lists.declining')} icon={TrendingDown} rows={data.declining} empty={t('commandCenter.lists.noneDeclining')} onOpen={(id) => navigate(productPath(id))}
            render={(p) => <><span className="apex-num apex-muted">{t('commandCenter.lists.units', { now: number.format(p.units), before: number.format(p.units_prev) })}</span><Delta value={p.units_change_pct} /></>} />
          <ProductList title={t('commandCenter.lists.restock')} icon={Boxes} rows={data.restock} empty={t('commandCenter.lists.noneRestock')} onOpen={(id) => navigate(productPath(id))}
            footer={data.restock_total > data.restock.length ? <ApexButton size="sm" variant="ghost" onClick={() => navigate(routePaths.forecasts)}>{t('commandCenter.lists.allRestock', { count: data.restock_total })}</ApexButton> : null}
            render={(p) => <><Pill tone={p.priority === 'high' ? 'danger' : 'warning'}>{t('demandApex.table.days', { count: number.format(Math.round(p.days_of_cover ?? 0)) })}</Pill><span className="apex-muted apex-num">{t('commandCenter.lists.order', { qty: number.format(p.suggested_qty) })}</span></>} />
        </div>

        <div className="apex-grid apex-grid--2">
          <Panel eyebrow={t('commandCenter.market.eyebrow')} title={t('commandCenter.market.movesTitle')} actions={<ApexButton size="sm" variant="ghost" onClick={() => navigate(routePaths.market)}>{t('commandCenter.market.all')}<ArrowRight size={14} className="apex-flip-rtl" /></ApexButton>}>
            {data.competitor_moves.length === 0 ? <StateBlock compact title={t('commandCenter.market.noMoves')} description={t('commandCenter.market.noMovesHint')} /> : (
              <ul className="cc-list">
                {data.competitor_moves.map((move, index) => (
                  <li key={index}>
                    <div>
                      <strong>{move.competitor}</strong>
                      <span className="apex-muted">{t('commandCenter.market.moveLine', { product: move.product, from: money(move.previous_price, move.currency, 2), to: money(move.price, move.currency, 2) })}</span>
                    </div>
                    <Delta value={move.change_pct} />
                  </li>
                ))}
              </ul>
            )}
          </Panel>
          <Panel eyebrow={t('commandCenter.market.eyebrow')} title={t('commandCenter.market.priceTitle')} actions={<ApexButton size="sm" variant="ghost" onClick={() => navigate(routePaths.pricing)}>{t('businessShell.navigation.pricing')}<ArrowRight size={14} className="apex-flip-rtl" /></ApexButton>}>
            {data.price_opportunities.length === 0 ? <StateBlock compact title={t('commandCenter.market.noGaps')} description={t('commandCenter.market.noGapsHint')} /> : (
              <ul className="cc-list">
                {data.price_opportunities.map((o) => (
                  <li key={o.product_id}>
                    <div>
                      <button type="button" className="apex-table__link" onClick={() => navigate(productPath(o.product_id))}>{o.name}</button>
                      <span className="apex-muted">{t(o.kind === 'above_market' ? 'commandCenter.market.above' : 'commandCenter.market.below', { yours: money(o.your_price, o.currency, 2), average: money(o.market_average, o.currency, 2), count: o.competitors, competitor: o.cheapest_competitor })}</span>
                    </div>
                    <Pill tone={o.kind === 'above_market' ? 'warning' : 'success'}>{o.gap_pct > 0 ? '+' : ''}{number.format(o.gap_pct)}%</Pill>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
        <p className="apex-source"><BarChart3 size={13} aria-hidden="true" />{t('commandCenter.sources')}</p>
      </div>
    </BusinessPageContainer>
  );
}

function ProductList({ title, icon: Icon, rows, empty, render, onOpen, footer }) {
  return (
    <Panel title={<span className="cc-list-title"><Icon size={15} aria-hidden="true" />{title}</span>}>
      {rows.length === 0 ? <StateBlock compact title={empty} /> : (
        <ul className="cc-list">
          {rows.map((row) => (
            <li key={row.product_id}>
              <button type="button" className="apex-table__link cc-list__name" onClick={() => onOpen(row.product_id)}>{row.name}</button>
              <span className="cc-list__value">{render(row)}</span>
            </li>
          ))}
        </ul>
      )}
      {footer}
    </Panel>
  );
}

export default CommandCenterPage;
