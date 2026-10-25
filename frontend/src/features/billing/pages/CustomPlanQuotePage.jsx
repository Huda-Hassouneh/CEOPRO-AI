import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { ArrowLeft, Check, LockKeyhole, X } from 'lucide-react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import Button from '../../../shared/components/ui/Button.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import Toast from '../../../shared/components/ui/Toast.jsx';
import { customOffersApi, createIdempotencyKey } from '../api/customOffersApi.js';
import { usePlans } from '../hooks/usePlans.js';
import { quoteHasVerifiedActivation } from '../utils/customQuoteState.js';
import '../styles/Billing.css';
import '../styles/PlansSubscription.css';
import '../styles/CustomPlan.css';

const tr = (t, key, fallback) => { const value = t(key); return value === key ? fallback : value; };
const safeReturnPath = (value) => value === routePaths.onboardingPlan ? routePaths.onboardingPlan : routePaths.billing;

export function CustomPlanQuotePage() {
  const { quoteId } = useParams();
  const { t, locale, dir } = useI18n();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const queryClient = useQueryClient();
  const returnTo = safeReturnPath(params.get('returnTo'));
  const backToBuilder = routePaths.customPlanBuilder + '?returnTo=' + encodeURIComponent(returnTo);
  const quoteQuery = useQuery({ queryKey: ['custom-offer-quote', quoteId], queryFn: () => customOffersApi.getQuote(quoteId), enabled: Boolean(quoteId) });
  const plansQuery = usePlans();
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState('');
  const transition = useMutation({
    mutationFn: ({ action, body }) => action === 'accept' ? customOffersApi.acceptQuote(quoteId, body) : customOffersApi.rejectQuote(quoteId, body),
    onSuccess: async (result) => {
      setError('');
      setNotice({ variant: 'success', message: result?.access_activated === false ? t('billing.customPlan.acceptedNotActivated') : t('billing.customPlan.transitionSaved') });
      await Promise.all([queryClient.invalidateQueries({ queryKey: ['custom-offer-quote', quoteId] }), queryClient.invalidateQueries({ queryKey: ['custom-offer-quotes'] })]);
    },
    onError: (cause) => setError(cause?.response?.data?.detail?.message || t('billing.customPlan.transitionFailed')),
  });
  const quote = quoteQuery.data;
  const isApproved = quote?.state === 'approved' && quote?.revision_state === 'approved';
  const isAccepted = quote?.state === 'accepted' && quote?.revision_state === 'accepted';
  const wasPaid = quoteHasVerifiedActivation(quote);
  const terms = quote?.commercial_terms || {};
  const checkoutSupported = terms.currency === 'USD' && String(terms.billingPeriodMonths) === '1' && Number(terms.monthlyPriceUsd) > 0;
  const checkoutAvailable = Boolean(checkoutSupported && plansQuery.data?.paymentsEnabled && isAccepted);
  const checkout = useMutation({
    mutationFn: () => customOffersApi.createCheckoutAttempt(quoteId, { idempotency_key: createIdempotencyKey() }),
    onSuccess: (result) => {
      if (result?.url && /^https:\/\//i.test(result.url)) window.location.assign(result.url);
      else setError(t('billing.customPlan.checkoutUnavailable'));
    },
    onError: (cause) => setError(cause?.response?.data?.detail?.message || t('billing.customPlan.checkoutUnavailable')),
  });

  const runTransition = (action) => {
    setError('');
    transition.mutate({ action, body: { expected_revision: Number(quote.revision_number), idempotency_key: createIdempotencyKey() } });
  };
  const displayCode = (code) => {
    const key = 'billing.modules.' + code;
    return tr(t, key, code.replaceAll('_', ' '));
  };
  const quantities = quote?.feature_quantities || {};
  const included = quote?.configuration?.enabledFeatures || quote?.configuration?.enabled_features || [];

  if (quoteQuery.isPending) return <div className="billing-management-loading" aria-busy="true"><Skeleton height="80px" /><Skeleton height="300px" /></div>;
  if (quoteQuery.isError || !quote) return <EmptyState title={t('billing.customPlan.quoteUnavailableTitle')} description={quoteQuery.error?.response?.data?.detail?.message || t('billing.customPlan.quoteUnavailableBody')} action={<Button onClick={() => navigate(backToBuilder)}>{t('billing.customPlan.back')}</Button>} />;

  return <div className="billing-management-page custom-plan-page" dir={dir}>
    <Link className="billing-back-link" to={backToBuilder}><ArrowLeft className="ceopro-setup-direction-icon" size={15} />{t('billing.customPlan.backToBuilder')}</Link>
    <PageHeader title={t('billing.customPlan.quoteTitle')} subtitle={t('billing.customPlan.quoteReference', { id: quote.quote_id })} />
    {notice && <div className="billing-management-toast"><Toast variant={notice.variant} message={notice.message} onClose={() => setNotice(null)} /></div>}
    {error && <p className="billing-provider-note is-warning" role="alert">{error}</p>}
    <section className="billing-payment-boundary custom-plan-offer-status">
      <LockKeyhole size={25} aria-hidden="true" />
      <h2>{t('billing.customPlan.status.' + (quote.state || 'submitted'))}</h2>
      {isApproved && <p>{t('billing.customPlan.offerReady')}</p>}
      {isAccepted && <p>{t(wasPaid ? 'billing.customPlan.paymentConfirmed' : 'billing.customPlan.acceptedNotActivated')}</p>}
      {quote.state === 'submitted' && <p>{t('billing.customPlan.reviewPending')}</p>}
      {quote.state === 'rejected' && <p>{t('billing.customPlan.offerRejected')}</p>}
      {quote.state === 'expired' && <p>{t('billing.customPlan.offerExpired')}</p>}
      {quote.valid_until && <small>{t('billing.customPlan.validUntil', { date: new Date(quote.valid_until).toLocaleDateString(locale) })}</small>}
    </section>
    <section className="billing-management-section custom-plan-offer-terms">
      <header><h2>{t('billing.customPlan.offerTerms')}</h2></header>
      <ul>{included.map((code) => <li key={code}><Check size={15} />{displayCode(code)}</li>)}{Object.entries(quantities).map(([code, value]) => <li key={code}><Check size={15} />{displayCode(code)}: {new Intl.NumberFormat(locale).format(value)}</li>)}</ul>
      {(isApproved || isAccepted) && terms.currency && terms.monthlyPriceUsd && <div className="custom-plan-price"><span>{t('billing.customPlan.approvedPrice')}</span><strong>{new Intl.NumberFormat(locale, { style: 'currency', currency: terms.currency }).format(Number(terms.monthlyPriceUsd))}{terms.billingPeriodMonths ? ' / ' + t('billing.customPlan.month') : ''}</strong></div>}
      {(isApproved || isAccepted) && <p className="billing-provider-note" role="note">{t('billing.customPlan.priceIsApprovedOffer')}</p>}
    </section>
    {(isApproved || isAccepted) && <div className="custom-plan-offer-actions">
      {isApproved && <Button variant="primary" loading={transition.isPending} disabled={transition.isPending} onClick={() => runTransition('accept')}><Check size={15} />{t('billing.customPlan.acceptOffer')}</Button>}
      {isApproved && <Button variant="outline" loading={transition.isPending} disabled={transition.isPending} onClick={() => runTransition('reject')}><X size={15} />{t('billing.customPlan.rejectOffer')}</Button>}
      {isAccepted && !wasPaid && <Button variant="primary" loading={checkout.isPending} disabled={!checkoutAvailable || checkout.isPending} onClick={() => checkout.mutate()}>{t(checkoutAvailable ? 'billing.customPlan.continueCheckout' : 'billing.customPlan.checkoutUnavailable')}</Button>}
      {isAccepted && wasPaid && <Link className="billing-link-button" to={routePaths.billing}>{t('billing.customPlan.manageSubscription')}</Link>}
      {isAccepted && !wasPaid && !checkoutAvailable && <p className="billing-provider-note" role="note">{!plansQuery.data?.paymentsEnabled ? t('billing.customPlan.checkoutPaymentsDisabled') : !checkoutSupported ? t('billing.customPlan.checkoutTermsUnsupported') : t('billing.customPlan.checkoutUnavailable')}</p>}
    </div>}
    {quote.state !== 'approved' && quote.state !== 'accepted' && <Button variant="outline" onClick={() => navigate(backToBuilder)}>{t('billing.customPlan.backToRequests')}</Button>}
    <p className="custom-plan-no-access" role="note">{t('billing.customPlan.noActivationNotice')}</p>
  </div>;
}
