import { useEffect } from 'react';
import { journeyState, journeyCheckoutUrl } from '../utils/subscriptionJourneyState.js';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../../auth/store/authStore.js';
import { subscriptionJourneyApi as api, journeyRequestKey, subscriptionJourneyEnabled } from '../api/subscriptionJourneyApi.js';
import { TrialJourneyPreview } from './TrialJourneyPreview.jsx';
import { TrialConsentPanel } from './TrialConsentPanel.jsx';

export function SubscriptionJourney({ plan, period }) {
  const tenant = useAuthStore((s) => s.tenantId);
  const actor = useAuthStore((s) => s.user?.id);
  if (!tenant || !actor) return null;
  return <Journey key={`${tenant}:${actor}:${plan}:${period}`} {...{ tenant, actor, plan, period }} />;
}

function Journey({ tenant, actor, plan, period }) {
  const { t, locale, dir } = useI18n();
  const [params, setParams] = useSearchParams();
  const operation = params.get('trial_operation');
  const queries = useQueryClient();
  const start = useMutation({ retry: false, mutationFn: () => api.start(plan, period, journeyRequestKey(tenant, actor, plan, period)),
    onSuccess: (data) => { const next = new URLSearchParams(params); next.set('trial_operation', data.operation_id); setParams(next, { replace: true }); } });
  const progress = useQuery({ queryKey: ['subscriptionJourney', tenant, actor, operation],
    queryFn: ({ signal }) => api.progress(operation, signal), enabled: Boolean(operation),
    retry: false, staleTime: 0, gcTime: 0, refetchInterval: 10000 });
  const advance = useMutation({ retry: false, mutationFn: () => api.advance(operation, locale),
    onSuccess: (data) => {
      progress.refetch();
      // Server-owned provider URL is validated again before browser navigation.
      const url = journeyCheckoutUrl(data);
      if (url) window.location.assign(url);
    } });
  const cancel = useMutation({ retry: false, mutationFn: () => api.cancel(operation) });
  const cleanup = useMutation({ retry: false, mutationFn: () => api.cleanup(operation) });
  const state = journeyState(progress, advance);
  useEffect(() => {
    if (progress.data?.state === 'confirmed' && !progress.isError) {
      // Refresh the actual rights projection; a redirect/checkpoint cannot grant.
      queries.invalidateQueries({ queryKey: ['subscription', tenant] });
    }
  }, [progress.data?.state, progress.isError, queries, tenant]);
  return <section dir={dir} aria-label={t('billing.subscriptionJourney.title')}>
    <h2>{t('billing.subscriptionJourney.title')}</h2>
    <p>{t('billing.subscriptionJourney.notice')}</p>
    {!operation && <button type="button" disabled={!subscriptionJourneyEnabled || start.isPending} onClick={() => start.mutate()}>{t('billing.subscriptionJourney.prepare')}</button>}
    {operation && <>
      <TrialJourneyPreview operationId={operation} />
      <TrialConsentPanel operationId={operation} />
      <p role="status">{t(`billing.subscriptionJourney.states.${state}`)}</p>
      <button type="button" disabled={!subscriptionJourneyEnabled || advance.isPending || progress.isError || ['confirmed','expired','conflict'].includes(state)} onClick={() => advance.mutate()}>{t('billing.subscriptionJourney.continue')}</button>
      {progress.data?.state === 'confirmed' ? <button type="button" disabled={!subscriptionJourneyEnabled || cancel.isPending} onClick={() => cancel.mutate()}>{t('billing.subscriptionJourney.cancel')}</button>
        : <button type="button" disabled={!subscriptionJourneyEnabled || cleanup.isPending} onClick={() => cleanup.mutate()}>{t('billing.subscriptionJourney.cleanup')}</button>}
      {(cancel.data || cleanup.data) && <p role="status">{t(cancel.data?.state === 'cancellation_recorded' ? 'billing.subscriptionJourney.canceled' : 'billing.subscriptionJourney.blocked')}</p>}
    </>}
    {(start.isError || advance.isError || cancel.isError || cleanup.isError) && <p role="alert">{t('billing.subscriptionJourney.blocked')}</p>}
  </section>;
}
