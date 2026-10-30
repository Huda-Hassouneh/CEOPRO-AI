import {Navigate} from 'react-router-dom';
import {onboardingApi} from '../../onboarding/api/onboardingApi.js';
import {useAuthStore} from '../../auth/store/authStore.js';
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
  const tenant=useAuthStore(s=>s.tenantId);
  const setup=useQuery({queryKey:['onboarding-state',tenant,'checkout-return'],queryFn:onboardingApi.getState,enabled:Boolean(result),retry:false});
  const close = useMutation({ mutationFn: async () => (await httpClient.post('/billing/checkout/cancel-pending')).data });
  const query = useQuery({ queryKey: ['checkout-return', sessionId], enabled: result === 'success' && Boolean(sessionId),
    queryFn: async () => (await httpClient.get('/billing/checkout-status', { params: { session_id: sessionId } })).data,
    refetchInterval: (q) => q.state.data?.state === 'confirmed' || q.state.dataUpdateCount >= 20 ? false : 3000,
    retry: false,
  });
  if (!result) return null;
  if(setup.data && !setup.data.isComplete && setup.data.highestCompletedStep>=5){
    if(result==='success'&&query.data?.state==='confirmed')return <Navigate replace to={'/onboarding/plan/success?'+new URLSearchParams({session_id:sessionId})}/>;
    if(result==='cancelled')return <Navigate replace to="/onboarding/plan/failed"/>;
  }
  const key = result === 'cancelled' ? 'cancelled' : query.isError ? 'unavailable' : query.data?.state === 'confirmed' ? 'confirmed' : 'pending';
  return <div className="billing-inline-notice" role="status"><p>{t(`billing.returnState.${key}`)}</p>
    {result === 'cancelled' && <><Button size="sm" variant="outline" disabled={close.isSuccess} loading={close.isPending} onClick={() => close.mutate()}>{t('billing.returnState.closeCheckout')}</Button>
      {close.isSuccess && <p>{t('billing.returnState.closed')}</p>}
      {close.isError && <p role="alert">{close.error?.response?.data?.detail?.message || t('billing.returnState.unavailable')}</p>}</>}
    {result === 'success' && query.data?.state !== 'confirmed' && <Button size="sm" variant="outline" onClick={() => query.refetch()} loading={query.isFetching}>{t('billing.management.retry')}</Button>}
  </div>;
}
