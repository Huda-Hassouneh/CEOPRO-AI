import { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { ExternalLink, Search, ShieldCheck, Star } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { ApexButton, Pill } from '../../../shared/components/apex/Apex.jsx';
import { PRICE_REASON_CODES } from '../api/competitorDataApi.js';
import { useFindMissingPrices } from '../hooks/useCompetitorData.js';
import { BarcodeEditor } from './BarcodeEditor.jsx';

// For one product: does it have a market price and from what, the public listings behind it
// (seller, price, the listing's own rating and review count), why there is none when there is
// none, and the two things the owner can do about it - look prices up, enter the barcode.
export function ProductMarketDetail({ product, competitors, currency }) {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const find = useFindMissingPrices();
  const number = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  const money = (amount, cur) => (amount == null || !cur ? '—' : new Intl.NumberFormat(locale, { style: 'currency', currency: cur }).format(amount));
  const coverage = competitors.price_coverage;
  const references = competitors.reference_prices || [];
  const range = competitors.reference_market;
  const gap = coverage && !coverage.has_market_price;
  const findNote = find.isError ? t('competitorData.coverage.findFailed') : find.data ? (find.data.already_queued ? t('competitorData.coverage.findAlready') : t('competitorData.coverage.findStarted')) : '';

  return (
    <div className="product-market-detail">
      <div className="product-market-detail__head">
        <div>
          <p className="apex-eyebrow">{t('competitorData.product.eyebrow')}</p>
          <h3>{t('competitorData.product.title')}</h3>
          <p className="apex-muted">{t('competitorData.product.subtitle')}</p>
        </div>
        <div className="product-market-detail__basis">
          <span className="apex-muted">{t('competitorData.product.basis')}</span>
          {coverage?.has_market_price
            ? <Pill tone="success">{t(`competitorData.coverage.basis.${coverage.price_basis}`)}</Pill>
            : <Pill tone="warning">{t('competitorData.product.none')}</Pill>}
        </div>
      </div>

      {gap && (
        <div className="product-market-detail__gap">
          <p>{t(PRICE_REASON_CODES.includes(coverage.reason_code) ? `competitorData.coverage.reasons.${coverage.reason_code}` : 'competitorData.reason.UNKNOWN')}</p>
          <div className="product-market-detail__actions">
            <ApexButton size="sm" icon={Search} loading={find.isPending} onClick={() => find.mutate()}>{find.isPending ? t('competitorData.coverage.finding') : t('competitorData.coverage.find')}</ApexButton>
            {coverage.action === 'review_source' && <ApexButton size="sm" variant="secondary" icon={ShieldCheck} onClick={() => navigate(routePaths.marketPendingSources)}>{t('competitorData.reviewTerms')}</ApexButton>}
          </div>
          <p className="apex-muted" role="status" aria-live="polite">{findNote}</p>
        </div>
      )}

      {range && (
        <p className="product-market-detail__range apex-muted">
          {t('competitorData.product.referenceRange', { low: money(range.lowest, currency), avg: money(range.average, currency), high: money(range.highest, currency), count: number.format(range.count) })}
        </p>
      )}

      {references.length === 0 ? null : (
        <div className="apex-table-wrap">
          <table className="apex-table">
            <thead><tr>
              <th>{t('competitorData.product.seller')}</th>
              <th className="apex-table__num">{t('competitorData.product.price')}</th>
              <th className="apex-table__num">{t('competitorData.product.rating')}</th>
              <th>{t('competitorData.product.listing')}</th>
            </tr></thead>
            <tbody>
              {references.map((ref, index) => (
                <tr key={`${ref.seller}-${index}`} className={ref.counted ? undefined : 'is-muted'}>
                  <td dir="auto">{ref.seller || '—'}</td>
                  <td className="apex-table__num apex-table__primary">{money(ref.price, ref.currency)}</td>
                  <td className="apex-table__num">
                    {ref.rating != null ? <span><Star size={12} aria-hidden="true" /> {number.format(ref.rating)}{ref.review_count ? <span className="apex-muted"> · {t('competitorData.product.reviews', { count: number.format(ref.review_count) })}</span> : null}</span> : '—'}
                  </td>
                  <td>
                    {ref.counted ? <Pill tone="success">{t('competitorData.product.counted')}</Pill> : <Pill tone="warning">{t('competitorData.product.notCounted')}</Pill>}
                    {ref.url && <a className="apex-inline-link" href={ref.url} target="_blank" rel="noreferrer noopener" aria-label={t('competitorData.product.open')}><ExternalLink size={12} aria-hidden="true" /></a>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <BarcodeEditor productId={product.product_id} value={product.barcode || null} />
    </div>
  );
}

export default ProductMarketDetail;
