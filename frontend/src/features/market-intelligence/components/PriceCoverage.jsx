import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowUpRight, CircleAlert, CircleOff, Clock, Coins, PlusCircle, Search, ShieldCheck, Unlink } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { ApexButton, Panel, Pill, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import { PRICE_REASON_CODES } from '../api/competitorDataApi.js';
import { useFindMissingPrices, usePriceCoverage } from '../hooks/useCompetitorData.js';
import { BarcodeEditor } from './BarcodeEditor.jsx';

const MODES = ['gaps', 'barcodes'];
const LIST_LIMIT = 500;

// What each listed product needs, as filters over the list. Counts come from
// the summary, which always covers every product. Each one is shown as the
// dashboard's stat tile (apex-stat), so the boxes match across the app.
const FILTERS = [
  { key: 'all', tone: 'accent', Icon: CircleAlert, count: (s) => s.needs_attention, match: () => true },
  { key: 'missing', tone: 'danger', Icon: CircleOff, count: (s) => s.without_market_price, match: (r) => !r.has_market_price },
  { key: 'approval', tone: 'violet', Icon: ShieldCheck, count: (s) => s.gaps_by_reason?.TERMS_UNREVIEWED || 0, match: (r) => r.reason_code === 'TERMS_UNREVIEWED' },
  { key: 'stale', tone: 'warning', Icon: Clock, count: (s) => s.stale_prices || 0, match: (r) => r.issues?.includes('stale') },
  { key: 'currency', tone: 'success', Icon: Coins, count: (s) => s.currency_mismatches || 0, match: (r) => r.issues?.includes('currency_mismatch') },
  { key: 'inactive', tone: 'accent', Icon: Unlink, count: (s) => s.inactive_mappings || 0, match: (r) => r.issues?.includes('inactive_mapping') },
];

// Where each recommended next step is done (price_coverage.py next_action).
const PRODUCT_ACTIONS = new Set(['enter_price', 'check_collection', 'refresh_prices', 'check_currency', 'review_mappings']);

function CoverageRing({ pct, label }) {
  const radius = 52;
  const circumference = 2 * Math.PI * radius;
  const filled = pct == null ? 0 : Math.max(0, Math.min(100, pct)) / 100;
  return (
    <div className="price-coverage__ring" role="img" aria-label={label}>
      <svg viewBox="0 0 128 128" aria-hidden="true">
        <defs>
          <linearGradient id="price-coverage-ring" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="var(--keel-logo-plain-stem-top)" />
            <stop offset=".6" stopColor="var(--keel-logo-plain-arm)" />
            <stop offset="1" stopColor="var(--keel-logo-plain-tip)" />
          </linearGradient>
        </defs>
        <circle className="price-coverage__ring-track" cx="64" cy="64" r={radius} />
        <circle className="price-coverage__ring-value" cx="64" cy="64" r={radius}
          strokeDasharray={`${circumference * filled} ${circumference}`} transform="rotate(-90 64 64)" />
      </svg>
      <span className="price-coverage__ring-label">{label}</span>
    </div>
  );
}

export function PriceCoverage() {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const [mode, setMode] = useState('gaps');
  const [filter, setFilter] = useState('all');
  const query = usePriceCoverage({ missingBarcode: mode === 'barcodes', limit: LIST_LIMIT });
  const find = useFindMissingPrices();
  const number = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  const date = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }), [locale]);
  const money = (amount, currency) => (amount == null || !currency ? '—' : new Intl.NumberFormat(locale, { style: 'currency', currency }).format(amount));
  const productPath = (id) => routePaths.productDetail.replace(':productId', id);

  const summary = query.data?.summary;
  const allRows = query.data?.products || [];
  const active = FILTERS.find((f) => f.key === filter) || FILTERS[0];
  const rows = mode === 'gaps' ? allRows.filter(active.match) : allRows;
  const findNote = find.isError ? t('competitorData.coverage.findFailed') : find.data ? (find.data.already_queued ? t('competitorData.coverage.findAlready') : t('competitorData.coverage.findStarted')) : '';
  const share = (count) => (summary?.total_products ? `${(count / summary.total_products) * 100}%` : '0%');

  const nextStep = (row) => {
    const action = mode === 'barcodes' ? 'add_barcode' : row.next_action;
    if (action === 'add_barcode') return <BarcodeEditor productId={row.product_id} compact />;
    if (action === 'review_source') return <ApexButton size="sm" variant="ghost" icon={ShieldCheck} onClick={() => navigate(routePaths.marketPendingSources)}>{t('competitorData.coverage.actions.review_source')}</ApexButton>;
    if (action === 'add_competitor') return <ApexButton size="sm" variant="ghost" icon={PlusCircle} onClick={() => navigate(routePaths.marketAddCompetitor)}>{t('competitorData.coverage.actions.add_competitor')}</ApexButton>;
    if (PRODUCT_ACTIONS.has(action)) {
      return <ApexButton size="sm" variant="ghost" icon={ArrowUpRight} className="price-coverage__go" onClick={() => navigate(productPath(row.product_id))}>{t(`competitorData.coverage.actions.${action}`)}</ApexButton>;
    }
    return <span className="apex-muted">—</span>;
  };

  const why = (row) => {
    const lines = [];
    if (!row.has_market_price) {
      lines.push(<div key="reason">{t(PRICE_REASON_CODES.includes(row.reason_code) ? `competitorData.coverage.reasons.${row.reason_code}` : 'competitorData.reason.UNKNOWN')}</div>);
      lines.push(
        <div key="lookup" className="apex-muted price-coverage__lookup">
          {row.market_lookup
            ? t('competitorData.coverage.lastLookup', { outcome: t(`competitorData.coverage.lookup.${row.market_lookup.outcome}`), date: date.format(new Date(row.market_lookup.last_attempt_at)) })
            : t('competitorData.coverage.neverSearched')}
        </div>,
      );
    }
    if (row.issues?.includes('stale')) lines.push(<div key="stale">{t('competitorData.coverage.issueText.stale', { days: number.format(row.price_age_days), limit: number.format(summary.stale_after_days) })}</div>);
    if (row.issues?.includes('currency_mismatch')) lines.push(<div key="currency">{t('competitorData.coverage.issueText.currency_mismatch', { count: number.format(row.foreign_currency_prices), currency: row.currency || '—' })}</div>);
    if (row.issues?.includes('inactive_mapping')) lines.push(<div key="inactive">{t('competitorData.coverage.issueText.inactive_mapping', { count: number.format(row.inactive_mappings) })}</div>);
    return lines;
  };

  return (
    <Panel
      eyebrow={t('competitorData.coverage.eyebrow')}
      title={t('competitorData.coverage.title')}
      subtitle={t('competitorData.coverage.subtitle')}
      className="price-coverage"
      bodyClassName="is-flush"
      actions={(
        <>
          <div className="apex-segmented" role="group" aria-label={t('competitorData.coverage.title')}>
            {MODES.map((key) => <button key={key} type="button" aria-pressed={mode === key} onClick={() => setMode(key)}>{t(`competitorData.coverage.${key === 'gaps' ? 'onlyGaps' : 'onlyBarcodes'}`)}</button>)}
          </div>
          <ApexButton size="sm" icon={Search} loading={find.isPending} onClick={() => find.mutate()}>
            {find.isPending ? t('competitorData.coverage.finding') : t('competitorData.coverage.find')}
          </ApexButton>
        </>
      )}
    >
      {query.isPending ? <StateBlock kind="loading" compact title={t('common.loading')} />
        : query.isError ? <StateBlock kind="error" compact title={t('competitorData.coverage.error')} onRetry={() => query.refetch()} retryLabel={t('demandApex.actions.retry')} />
          : (
            <>
              <div className="price-coverage__overview">
                <CoverageRing pct={summary.coverage_pct} label={summary.coverage_pct == null ? '—' : `${number.format(summary.coverage_pct)}%`} />
                <div className="price-coverage__headline">
                  <p className="price-coverage__headline-main">
                    {t('competitorData.coverage.headline', { covered: number.format(summary.with_market_price), total: number.format(summary.total_products) })}
                  </p>
                  <div className="price-coverage__bar" aria-hidden="true">
                    <span className="is-competitor" style={{ width: share(summary.with_competitor_price) }} />
                    <span className="is-reference" style={{ width: share(summary.with_reference_price_only) }} />
                    <span className="is-missing" style={{ width: share(summary.without_market_price) }} />
                  </div>
                  <ul className="price-coverage__legend">
                    <li><span className="price-coverage__dot is-competitor" />{t('competitorData.coverage.stats.competitor')} <strong>{number.format(summary.with_competitor_price)}</strong></li>
                    <li><span className="price-coverage__dot is-reference" />{t('competitorData.coverage.stats.reference')} <strong>{number.format(summary.with_reference_price_only)}</strong></li>
                    <li><span className="price-coverage__dot is-missing" />{t('competitorData.coverage.stats.gaps')} <strong>{number.format(summary.without_market_price)}</strong></li>
                    <li><span className="price-coverage__dot is-barcode" />{t('competitorData.coverage.stats.barcodes')} <strong>{number.format(summary.products_without_barcode)}</strong></li>
                  </ul>
                  <p className="price-coverage__honesty apex-muted">{t('competitorData.coverage.honesty')}</p>
                </div>
              </div>

              {mode === 'gaps' && (
                <div className="price-coverage__filters" role="group" aria-label={t('competitorData.coverage.filtersLabel')}>
                  {FILTERS.map(({ key, tone, Icon, count: countOf }) => {
                    const count = countOf(summary);
                    return (
                      <button key={key} type="button" className={`apex-stat apex-stat--${tone} price-coverage__filter`} aria-pressed={filter === key} onClick={() => setFilter(key)} disabled={!count && key !== 'all'}>
                        <span className="apex-stat__top">
                          <span className="apex-stat__label">{t(`competitorData.coverage.filters.${key}`)}</span>
                          <span className="apex-stat__icon" aria-hidden="true"><Icon size={16} /></span>
                        </span>
                        <strong className="apex-stat__value apex-num">{number.format(count)}</strong>
                      </button>
                    );
                  })}
                </div>
              )}

              <p className="price-coverage__note apex-muted" role="status" aria-live="polite">{findNote}</p>
              {rows.length === 0 ? <StateBlock compact title={t(mode === 'gaps' ? (filter === 'all' ? 'competitorData.coverage.allCovered' : 'competitorData.coverage.noneInFilter') : 'competitorData.coverage.noBarcodes')} /> : (
                <div className="apex-table-wrap">
                  <table className="apex-table price-coverage__table">
                    <thead><tr>
                      <th>{t('competitorData.coverage.product')}</th>
                      <th>{t('competitorData.coverage.statusColumn')}</th>
                      <th>{t('competitorData.coverage.why')}</th>
                      <th>{t('competitorData.coverage.nextStep')}</th>
                    </tr></thead>
                    <tbody>
                      {rows.map((row) => (
                        <tr key={row.product_id}>
                          <td className="price-coverage__product">
                            <button type="button" className="apex-table__link" onClick={() => navigate(productPath(row.product_id))}>{row.product_name}</button>
                            <div className="apex-muted price-coverage__price"><bdi>{money(row.your_price, row.currency)}</bdi></div>
                          </td>
                          <td data-label={t('competitorData.coverage.statusColumn')}>
                            <div className="price-coverage__badges">
                              {row.has_market_price
                                ? <Pill tone="success">{t(`competitorData.coverage.basis.${row.price_basis}`)}</Pill>
                                : <Pill tone="danger">{t('competitorData.coverage.status.missing')}</Pill>}
                              {row.reason_code === 'TERMS_UNREVIEWED' && <Pill tone="warning">{t('competitorData.coverage.filters.approval')}</Pill>}
                              {row.issues?.includes('stale') && <Pill tone="warning">{t('competitorData.coverage.badge.stale', { days: number.format(row.price_age_days) })}</Pill>}
                              {row.issues?.includes('currency_mismatch') && <Pill tone="violet">{t('competitorData.coverage.badge.currency_mismatch')}</Pill>}
                              {row.issues?.includes('inactive_mapping') && <Pill tone="neutral">{t('competitorData.coverage.badge.inactive_mapping')}</Pill>}
                            </div>
                          </td>
                          <td className="price-coverage__why" data-label={t('competitorData.coverage.why')}>{why(row)}</td>
                          <td className="price-coverage__next" data-label={t('competitorData.coverage.nextStep')}>{nextStep(row)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
    </Panel>
  );
}

export default PriceCoverage;
