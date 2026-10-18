import { useEffect } from 'react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import Modal from '../../../shared/components/ui/Modal.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import Badge from '../../../shared/components/ui/Badge.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import { usePriceRecommendation } from '../hooks/usePriceRecommendation.js';

const ACTION_BADGE_VARIANT = { raise: 'success', lower: 'warning', hold: 'neutral' };

// backend/src/ai/routers/pricing.py's POST /pricing/recommend - a real,
// rule-based comparison against real scraped competitor prices for this
// one product, with real price-change/minimum-margin guardrails. Fetched
// on demand (a mutation, not an auto-loading query) since it's a real
// write - it persists an evidence_records + recommendation_outcomes row
// every time it runs, not a free read.
export function PriceRecommendationModal({ open, product, onClose, currencyFormatter, t }) {
  const { locale } = useI18n();
  const mutation = usePriceRecommendation();

  useEffect(() => {
    if (open && product) mutation.mutate(product.product_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, product?.product_id]);

  if (!product) return null;
  const result = mutation.data;
  const number = (value) => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(Number(value ?? 0));

  return <Modal isOpen={open} onClose={onClose} title={t('pricing.modal.title', { name: product.product_name })} closeLabel={t('common.close')} maxWidth="520px">
    {mutation.isPending && <Skeleton height="180px" variant="rectangular" />}
    {mutation.isError && <EmptyState title={t('pricing.modal.errorTitle')} description={t('pricing.modal.errorDescription')} action={<Button size="sm" variant="outline" onClick={() => mutation.mutate(product.product_id)}>{t('pricing.modal.retry')}</Button>} />}

    {result?.status === 'UNKNOWN' && <EmptyState title={t('pricing.modal.unknownTitle')} description={t('pricing.modal.unknownDescription', { days: result.max_price_age_days ?? 30 })} />}

    {result?.status === 'OK' && <div className="pricing-recommendation-result">
      <div className="pricing-recommendation-headline">
        <Badge variant={ACTION_BADGE_VARIANT[result.action] || 'neutral'}>{t(`pricing.actions.${result.action}`)}</Badge>
        <div className="pricing-recommendation-prices">
          <span>{currencyFormatter(result.current_price, product.currency)}</span>
          <span aria-hidden="true">→</span>
          <strong>{currencyFormatter(result.suggested_price, product.currency)}</strong>
        </div>
      </div>
      <dl className="pricing-recommendation-meta">
        <div><dt>{t('pricing.modal.matchedCompetitors')}</dt><dd>{result.matched_competitor_count}</dd></div>
        <div><dt>{t('pricing.modal.confidence')}</dt><dd>{result.confidence_score != null ? `${Math.round(result.confidence_score * 100)}%` : t('products.common.notAvailable')}</dd></div>
      </dl>
      {(result.guardrail_clamped || result.margin_guardrail_clamped) && <p className="pricing-recommendation-guardrail-note">{t('pricing.modal.guardrailApplied')}</p>}
      {/* Never a bare "no data": a decision backed by an estimate says what it is estimated from. */}
      {result.data_basis && result.data_basis !== 'LOCAL_MARKET'
        ? <p className="pricing-recommendation-explanation pricing-recommendation-explanation--strong">{t(`pricing.modal.estimate.${result.data_basis}`)}</p>
        : <p className="pricing-recommendation-explanation">{t('pricing.modal.basis', { count: result.matched_competitor_count, days: result.max_price_age_days ?? 30 })}</p>}
      {/* The reasoning, built from the numbers so it reads in the interface language. */}
      {result.market && <p className="pricing-recommendation-explanation">{t(`pricing.reason.market.${result.market_action || result.action}`, {
        price: currencyFormatter(result.current_price, product.currency),
        average: currencyFormatter(result.market.average, product.currency),
        min: currencyFormatter(result.market.min, product.currency),
        max: currencyFormatter(result.market.max, product.currency),
        count: result.matched_competitor_count,
      })}</p>}
      {result.hold_reason && result.demand && <p className="pricing-recommendation-explanation pricing-recommendation-explanation--strong">{t(`pricing.reason.hold.${result.hold_reason}`, {
        stock: number(result.demand.stock),
        days: number(result.demand.days_of_cover),
        forecast: number(result.demand.forecast_next_30),
        pct: number(Math.abs(result.demand.sales_change_pct ?? 0)),
        recent: number(result.demand.sold_last_30),
        previous: number(result.demand.sold_previous_30),
      })}</p>}
    </div>}
  </Modal>;
}
