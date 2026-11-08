import { useEffect, useRef, useState } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { useAuthStore } from '../../auth/store/authStore.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { subscriptionJourneyApi as api, subscriptionJourneyEnabled } from '../api/subscriptionJourneyApi.js';
import { validTrialOperation } from '../api/trialJourneyApi.js';
import { openPaddleCheckout } from '../utils/paddleCheckout.js';

export function PaddlePaymentPage() {
  const tenant = useAuthStore(s => s.tenantId), actor = useAuthStore(s => s.user?.id);
  return <Payment key={`${tenant}:${actor}`} />;
}
function Payment() {
  const [params] = useSearchParams(), { t, locale, dir } = useI18n();
  const operation = params.get('trial_operation'), transaction = params.get('_ptxn');
  const controller = useRef(null);
  useEffect(() => () => controller.current?.abort(), [operation, transaction]);
  const [pending, setPending] = useState(false), [failed, setFailed] = useState(false);
  const enabled = subscriptionJourneyEnabled && import.meta.env.VITE_PADDLE_CHECKOUT_ENABLED === 'true' && validTrialOperation(operation)
    && params.getAll('trial_operation').length === 1 && params.getAll('_ptxn').length === 1;
  async function open() {
    const request = new AbortController();
    controller.current?.abort(); controller.current = request;
    setPending(true); setFailed(false);
    try {
      // Fresh server authorization on every explicit attempt, never a cached
      // identity/consent decision. Browser completion never changes access.
      const details = await api.checkout(operation, locale, request.signal);
      await openPaddleCheckout(details, operation, transaction, locale, undefined, request.signal);
    } catch { setFailed(true); }
    finally { setPending(false); }
  }
  return <section dir={dir} aria-label={t('billing.subscriptionJourney.title')}>
    <h1>{t('billing.subscriptionJourney.title')}</h1>
    <p>{t('billing.subscriptionJourney.notice')}</p>
    <button type="button" disabled={!enabled || pending} onClick={open}>{t('billing.subscriptionJourney.continue')}</button>
    {(!enabled || failed) && <p role="alert">{t('billing.subscriptionJourney.blocked')}</p>}
    <Link to="/billing">{t('billing.onboarding.backToPlans')}</Link>
  </section>;
}
