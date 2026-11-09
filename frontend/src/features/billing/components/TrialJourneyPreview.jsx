import { useQuery } from '@tanstack/react-query';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../../auth/store/authStore.js';
import { trialJourneyPreviewEnabled, trialPreviewQuery } from '../api/trialJourneyApi.js';

const states = new Set(['eligible', 'pending_verification', 'conflict', 'expired', 'blocked']);

export function TrialJourneyPreview({ operationId, enabled = trialJourneyPreviewEnabled }) {
  return enabled ? <EnabledPreview operationId={operationId} /> : null;
}

function EnabledPreview({ operationId }) {
  const { t, dir } = useI18n();
  const tenantId = useAuthStore((state) => state.tenantId);
  const userId = useAuthStore((state) => state.user?.id);
  const options = trialPreviewQuery(tenantId, userId, operationId, true);
  const query = useQuery(options);
  // Hide previous data during refresh/denial; cached status is never authority.
  const data = options.enabled && !query.isError && !query.isFetching ? query.data : null;
  const state = states.has(data?.state) ? data.state : 'blocked';
  const terms = data?.commercial_terms;
  return <section className="billing-payment-boundary" dir={dir} aria-label={t('billing.trialJourney.title')}>
    <h2>{t('billing.trialJourney.title')}</h2>
    <p role="status">{options.enabled && query.isFetching ? t('common.loading') : t(`billing.trialJourney.${state}`)}</p>
    {terms && <dl>
      <dt>{t('billing.trialJourney.plan')}</dt><dd>{terms.plan_key}</dd>
      <dt>{t('billing.trialJourney.renewal')}</dt><dd><bdi>{terms.renewal_amount} {terms.currency}</bdi></dd>
      <dt>{t('billing.trialJourney.interval')}</dt><dd>{t('billing.trialJourney.months', { count: terms.interval_months })}</dd>
      <dt>{t('billing.trialJourney.duration')}</dt><dd>{t('billing.trialJourney.days', { count: terms.trial_duration_days })}</dd>
    </dl>}
    <p>{t('billing.trialJourney.note')}</p>
  </section>;
}
