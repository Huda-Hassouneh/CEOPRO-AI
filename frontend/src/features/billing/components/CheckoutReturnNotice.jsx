import { useSearchParams } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import httpClient from '../../../shared/lib/httpClient.js';
import Button from '../../../shared/components/ui/Button.jsx';
export function CheckoutReturnNotice() {
  const [params] = useSearchParams();
  const { t } = useI18n();
  const result = params.get('checkout');
  const sessionId = params.get('session_id');
  const close = useMutation({ mutationFn: async () => (await httpClient.post('/billing/checkout/cancel-pending')).data });
  const query = useQuery({ queryKey: ['checkout-return', sessionId], enabled: result === 'success' && Boolean(sessionId),
    queryFn: async () => (await httpClient.get('/billing/checkout-status', { params: { session_id: sessionId } })).data,
    refetchInterval: (q) => q.state.data?.state === 'confirmed' || q.state.dataUpdateCount >= 20 ? false : 3000,
    retry: false,
  });
  if (!result) return null;
  const key = result === 'cancelled' ? 'cancelled' : query.isError ? 'unavailable' : query.data?.state === 'confirmed' ? 'confirmed' : 'pending';
  return <div className="billing-inline-notice" role="status"><p>{t(`billing.returnState.${key}`)}</p>
    {result === 'cancelled' && <><Button size="sm" variant="outline" disabled={close.isSuccess} loading={close.isPending} onClick={() => close.mutate()}>{t('billing.returnState.closeCheckout')}</Button>
      {close.isSuccess && <p>{t('billing.returnState.closed')}</p>}
      {close.isError && <p role="alert">{close.error?.response?.data?.detail?.message || t('billing.returnState.unavailable')}</p>}</>}
    {result === 'success' && query.data?.state !== 'confirmed' && <Button size="sm" variant="outline" onClick={() => query.refetch()} loading={query.isFetching}>{t('billing.management.retry')}</Button>}
  </div>;
}
