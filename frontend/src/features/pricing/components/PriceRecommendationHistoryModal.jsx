import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { pricingApi } from '../api/pricingApi.js';
import Modal from '../../../shared/components/ui/Modal.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';

const PAGE_SIZE = 10;

export function PriceRecommendationHistoryModal({ open, product, onClose, t, locale }) {
  const [offset, setOffset] = useState(0);
  useEffect(() => { setOffset(0); }, [product?.product_id, open]);
  const query = useQuery({
    queryKey: ['pricing', 'history', product?.product_id, offset],
    queryFn: () => pricingApi.recommendationHistory(product.product_id, { limit: PAGE_SIZE, offset }),
    enabled: open && Boolean(product?.product_id),
  });

  if (!product) return null;
  const items = query.data?.items ?? [];
  const dateFormatter = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' });

  return <Modal isOpen={open} onClose={onClose} title={t('pricing.history.title', { name: product.product_name })} closeLabel={t('common.close')} maxWidth="760px">
    <p className="pricing-history__note">{t('pricing.history.note')}</p>
    {query.isPending && <Skeleton height="220px" variant="rectangular" />}
    {query.isError && <EmptyState title={t('pricing.history.errorTitle')} description={t('pricing.history.errorDescription')} action={<Button size="sm" variant="outline" onClick={() => query.refetch()}>{t('pricing.history.retry')}</Button>} />}
    {query.isSuccess && items.length === 0 && <EmptyState title={t('pricing.history.emptyTitle')} description={t('pricing.history.emptyDescription')} />}
    {query.isSuccess && items.length > 0 && <>
      <ol className="pricing-history" aria-label={t('pricing.history.title', { name: product.product_name })}>
        {items.map((item) => <li className="pricing-history__item" key={item.evidence_id}>
          <div className="pricing-history__header">
            <strong>{item.recommended_action || t('pricing.history.incomplete')}</strong>
            <time dateTime={item.generated_at}>{item.generated_at ? dateFormatter.format(new Date(item.generated_at)) : t('products.common.notAvailable')}</time>
          </div>
          <div className="pricing-history__meta">
            <span>{t('pricing.history.decision')}: {t(`pricing.history.decisions.${item.user_decision || 'unknown'}`)}</span>
            {item.data_basis && <span>{t('pricing.history.basis')}: {t(`pricing.history.bases.${item.data_basis}`)}</span>}
            {item.confidence_score != null && <span>{t('pricing.modal.confidence')}: {Math.round(item.confidence_score * 100)}%</span>}
          </div>
          {item.explanation && <p>{item.explanation}</p>}
        </li>)}
      </ol>
      <nav className="pricing-history__pager" aria-label={t('pricing.history.pagination')}>
        <Button size="sm" variant="outline" disabled={offset === 0 || query.isFetching} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>{t('pricing.history.previous')}</Button>
        <span>{t('pricing.history.page', { page: Math.floor(offset / PAGE_SIZE) + 1 })}</span>
        <Button size="sm" variant="outline" disabled={!query.data.has_more || query.isFetching} onClick={() => setOffset(offset + PAGE_SIZE)}>{t('pricing.history.next')}</Button>
      </nav>
    </>}
  </Modal>;
}
