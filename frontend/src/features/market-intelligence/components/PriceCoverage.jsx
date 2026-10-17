import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, ShieldCheck } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { ApexButton, Panel, Pill, Stat, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import { PRICE_REASON_CODES } from '../api/competitorDataApi.js';
import { useFindMissingPrices, usePriceCoverage } from '../hooks/useCompetitorData.js';
import { BarcodeEditor } from './BarcodeEditor.jsx';

const MODES = ['gaps', 'barcodes'];

// Does every product have a market price? How many do, how many do not and why, with the
// next step for each: look prices up, review a competitor's terms, or enter a barcode.
export function PriceCoverage() {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const [mode, setMode] = useState('gaps');
  const query = usePriceCoverage({ missingBarcode: mode === 'barcodes', limit: 100 });
  const find = useFindMissingPrices();
  const number = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  const date = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }), [locale]);
  const money = (amount, currency) => (amount == null || !currency ? '—' : new Intl.NumberFormat(locale, { style: 'currency', currency }).format(amount));
  const productPath = (id) => routePaths.productDetail.replace(':productId', id);

  const summary = query.data?.summary;
  const rows = query.data?.products || [];
  const findNote = find.isError ? t('competitorData.coverage.findFailed') : find.data ? (find.data.already_queued ? t('competitorData.coverage.findAlready') : t('competitorData.coverage.findStarted')) : '';

  return (
    <Panel
      eyebrow={t('competitorData.coverage.eyebrow')}
      title={t('competitorData.coverage.title')}
      subtitle={t('competitorData.coverage.subtitle')}
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
              <div className="apex-grid apex-grid--stats price-coverage__stats">
                <Stat label={t('competitorData.coverage.stats.covered')} value={`${number.format(summary.with_market_price)} / ${number.format(summary.total_products)}`} hint={summary.coverage_pct != null ? `${number.format(summary.coverage_pct)}%` : undefined} tone={summary.without_market_price ? 'warning' : 'success'} />
                <Stat label={t('competitorData.coverage.stats.competitor')} value={number.format(summary.with_competitor_price)} tone="accent" />
                <Stat label={t('competitorData.coverage.stats.reference')} value={number.format(summary.with_reference_price_only)} tone="violet" />
                <Stat label={t('competitorData.coverage.stats.gaps')} value={number.format(summary.without_market_price)} tone={summary.without_market_price ? 'danger' : 'success'} />
                <Stat label={t('competitorData.coverage.stats.barcodes')} value={number.format(summary.products_without_barcode)} tone={summary.products_without_barcode ? 'warning' : 'success'} />
              </div>
              <p className="price-coverage__note apex-muted" role="status" aria-live="polite">{findNote}</p>
              {rows.length === 0 ? <StateBlock compact title={t(mode === 'gaps' ? 'competitorData.coverage.allCovered' : 'competitorData.coverage.noBarcodes')} /> : (
                <div className="apex-table-wrap">
                  <table className="apex-table">
                    <thead><tr>
                      <th>{t('competitorData.coverage.product')}</th>
                      <th className="apex-table__num">{t('competitorsApex.coverage.yours')}</th>
                      <th>{t('competitorData.coverage.reason')}</th>
                      <th>{t('competitorData.barcode.label')}</th>
                    </tr></thead>
                    <tbody>
                      {rows.map((row) => (
                        <tr key={row.product_id}>
                          <td><button type="button" className="apex-table__link" onClick={() => navigate(productPath(row.product_id))}>{row.product_name}</button></td>
                          <td className="apex-table__num apex-table__primary">{money(row.your_price, row.currency)}</td>
                          <td>
                            {row.has_market_price
                              ? <Pill tone="success">{t(`competitorData.coverage.basis.${row.price_basis}`)}</Pill>
                              : (
                                <>
                                  <div>{t(PRICE_REASON_CODES.includes(row.reason_code) ? `competitorData.coverage.reasons.${row.reason_code}` : 'competitorData.reason.UNKNOWN')}</div>
                                  <div className="apex-muted price-coverage__lookup">
                                    {row.market_lookup
                                      ? t('competitorData.coverage.lastLookup', { outcome: t(`competitorData.coverage.lookup.${row.market_lookup.outcome}`), date: date.format(new Date(row.market_lookup.last_attempt_at)) })
                                      : t('competitorData.coverage.neverSearched')}
                                  </div>
                                  {row.action === 'review_source' && (
                                    <ApexButton size="sm" variant="ghost" icon={ShieldCheck} onClick={() => navigate(routePaths.marketPendingSources)}>{t('competitorData.reviewTerms')}</ApexButton>
                                  )}
                                </>
                              )}
                          </td>
                          <td className="price-coverage__barcode">{row.has_barcode ? <Pill tone="success">{t('competitorData.barcode.label')} ✓</Pill> : <BarcodeEditor productId={row.product_id} compact />}</td>
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
