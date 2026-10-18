import { useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, MessageSquareText, Upload } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Toast from '../../../shared/components/ui/Toast.jsx';
import httpClient from '../../../shared/lib/httpClient.js';
import { useSubmitLock } from '../../../shared/hooks/useSubmitLock.js';

const TEMPLATE = 'date,rating,review,product,platform,customer\n2026-09-15,5,"Great quality and fast delivery",,Google Maps,Sara\n';

// POST /reviews/import + GET /reviews - the business's own customers'
// reviews (Google Maps / Facebook / booking-site exports, feedback forms).
// Sentiment is analysed in the background after an import, so the list
// polls until every review has a result.
export function CustomerReviewsSection({ t, locale }) {
  const queryClient = useQueryClient();
  const runLocked = useSubmitLock();
  const inputRef = useRef(null);
  const [importing, setImporting] = useState(false);
  const [notice, setNotice] = useState(null);
  const reviewsQuery = useQuery({
    queryKey: ['customer-reviews'],
    queryFn: async () => (await httpClient.get('/reviews', { params: { limit: 20 } })).data,
    refetchInterval: (query) => (query.state.data?.reviews?.some((review) => !review.sentiment) ? 5000 : false),
  });
  const date = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }), [locale]);
  const reviews = reviewsQuery.data?.reviews || [];

  const downloadTemplate = () => {
    const url = URL.createObjectURL(new Blob([TEMPLATE], { type: 'text/csv' }));
    const link = document.createElement('a');
    link.href = url; link.download = 'customer-reviews-template.csv';
    document.body.appendChild(link); link.click(); link.remove();
    URL.revokeObjectURL(url);
  };

  const onFile = (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    runLocked(async () => {
      setImporting(true);
      try {
        const formData = new FormData();
        formData.append('file', file);
        const { data } = await httpClient.post('/reviews/import', formData, { headers: { 'Content-Type': 'multipart/form-data' } });
        setNotice({
          variant: data.imported ? 'success' : 'info',
          message: t('connectData.reviews.summary', { imported: data.imported, duplicates: data.duplicates, skipped: data.skipped, linked: data.linked_to_products }),
        });
        queryClient.invalidateQueries({ queryKey: ['customer-reviews'] });
        queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      } catch (error) {
        setNotice({ variant: 'error', message: error?.response?.data?.detail && typeof error.response.data.detail === 'string' ? error.response.data.detail : t('connectData.reviews.failed') });
      } finally {
        setImporting(false);
      }
    });
  };

  return <section className="connect-data-section connect-data-reviews">
    <div className="connect-data-section__header"><div><h2>{t('connectData.reviews.title')}</h2><p>{t('connectData.reviews.subtitle')}</p></div>
      <div className="connect-data-reviews__actions">
        <Button size="sm" variant="outline" leadingIcon={<Download size={14} />} onClick={downloadTemplate}>{t('connectData.reviews.template')}</Button>
        <Button size="sm" leadingIcon={<Upload size={14} />} loading={importing} loadingLabel={t('connectData.reviews.importing')} onClick={() => inputRef.current?.click()}>{t('connectData.reviews.import')}</Button>
        <input ref={inputRef} type="file" accept=".csv,.xlsx,.xlsm" hidden onChange={onFile} />
      </div>
    </div>
    {reviews.length
      ? <div className="connect-data-table-wrap" tabIndex={0} role="region" aria-label={t('common.scrollableTable')}><table className="connect-data-table"><thead><tr><th>{t('connectData.reviews.date')}</th><th>{t('connectData.reviews.review')}</th><th>{t('connectData.reviews.product')}</th><th>{t('connectData.reviews.rating')}</th><th>{t('connectData.reviews.sentiment')}</th></tr></thead><tbody>{reviews.map((review) => <tr key={review.review_id}><td>{review.review_date ? date.format(new Date(review.review_date)) : '-'}</td><td><bdi>{review.text}</bdi><small className="connect-data-reviews__meta">{[review.reviewer, review.platform].filter(Boolean).join(' · ')}</small></td><td>{review.product_name || t('connectData.reviews.wholeBusiness')}</td><td>{review.rating != null ? `${review.rating} / 5` : '-'}</td><td><span className={`connect-data-sentiment is-${review.sentiment || 'pending'}`}>{t(`connectData.reviews.sentiments.${review.sentiment || 'pending'}`)}</span></td></tr>)}</tbody></table></div>
      : <EmptyState icon={<MessageSquareText size={24} />} title={t('connectData.reviews.emptyTitle')} description={t('connectData.reviews.emptyDescription')} />}
    {notice && <Toast variant={notice.variant} message={notice.message} onClose={() => setNotice(null)} />}
  </section>;
}
