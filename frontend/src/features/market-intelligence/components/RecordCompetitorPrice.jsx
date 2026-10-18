import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Button from '../../../shared/components/ui/Button.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import Select from '../../../shared/components/ui/Select.jsx';
import Toast from '../../../shared/components/ui/Toast.jsx';
import httpClient from '../../../shared/lib/httpClient.js';
import { productsApi } from '../../products/api/productsApi.js';
import { useSubmitLock } from '../../../shared/hooks/useSubmitLock.js';

// POST /competitors/{id}/prices - a price the owner saw themselves (store
// visit, phone call, flyer, marketplace listing). It feeds the same
// comparison, pricing recommendations and dashboard cards as scraped prices.
export function RecordCompetitorPrice({ competitorId, t }) {
  const queryClient = useQueryClient();
  const runLocked = useSubmitLock();
  const productsQuery = useQuery({ queryKey: ['products', 'select-all'], queryFn: () => productsApi.list({ limit: 200 }) });
  const [values, setValues] = useState({ productId: '', price: '', observedOn: '', url: '' });
  const [notice, setNotice] = useState(null);
  const products = useMemo(() => productsQuery.data?.products || [], [productsQuery.data]);
  const options = useMemo(() => [{ value: '', label: t('market.recordPrice.chooseProduct') }, ...products.map((product) => ({ value: product.product_id, label: `${product.product_name} (${product.currency})` }))], [products, t]);
  const mutation = useMutation({
    mutationFn: (payload) => httpClient.post(`/competitors/${encodeURIComponent(competitorId)}/prices`, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['competitor-profile', competitorId] });
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });
  const price = Number(values.price);
  const valid = Boolean(values.productId) && values.price !== '' && Number.isFinite(price) && price >= 0;

  const submit = (event) => {
    event.preventDefault();
    if (!valid) return;
    runLocked(async () => {
      try {
        await mutation.mutateAsync({
          product_id: values.productId,
          price,
          observed_at: values.observedOn ? new Date(`${values.observedOn}T12:00:00Z`).toISOString() : undefined,
          product_url: values.url.trim() || undefined,
        });
        setValues({ productId: values.productId, price: '', observedOn: '', url: '' });
        setNotice({ variant: 'success', message: t('market.recordPrice.saved') });
      } catch (error) {
        setNotice({ variant: 'error', message: error?.response?.status === 404 ? t('market.recordPrice.notFound') : t('market.recordPrice.failed') });
      }
    });
  };

  return <section className="market-panel competitor-record-price">
    <div className="market-panel__header"><div><h2>{t('market.recordPrice.title')}</h2><p>{t('market.recordPrice.subtitle')}</p></div></div>
    {products.length === 0 && !productsQuery.isPending
      ? <p className="market-empty-note">{t('market.recordPrice.noProducts')}</p>
      : <form className="competitor-record-price__form" onSubmit={submit}>
        <Select label={t('market.recordPrice.product')} value={values.productId} onChange={(event) => setValues({ ...values, productId: event.target.value })} options={options} disabled={mutation.isPending} />
        <Input type="number" min="0" step="any" label={t('market.recordPrice.price')} value={values.price} onChange={(event) => setValues({ ...values, price: event.target.value })} disabled={mutation.isPending} />
        <Input type="date" label={t('market.recordPrice.observedOn')} hint={t('market.recordPrice.observedOnHint')} value={values.observedOn} max={new Date().toISOString().slice(0, 10)} onChange={(event) => setValues({ ...values, observedOn: event.target.value })} disabled={mutation.isPending} />
        <Input type="url" label={t('market.recordPrice.url')} placeholder="https://" value={values.url} onChange={(event) => setValues({ ...values, url: event.target.value })} disabled={mutation.isPending} />
        <Button type="submit" size="sm" disabled={!valid} loading={mutation.isPending} loadingLabel={t('market.recordPrice.saving')}>{t('market.recordPrice.save')}</Button>
      </form>}
    {notice && <Toast variant={notice.variant} message={notice.message} onClose={() => setNotice(null)} />}
  </section>;
}
