import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
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
import { useAuthStore } from '../../auth/store/authStore.js';
import { useSubscription } from '../hooks/useSubscription.js';
import { hasActivePlanAccess } from '../utils/onboardingRouting.js';
import { usePlans } from '../hooks/usePlans.js';
import { quoteHasVerifiedActivation, quoteIsExpired, subscriptionBlocksCustomCheckout, quoteFeatureLabel } from '../utils/customQuoteState.js';
import '../styles/Billing.css';
import '../styles/PlansSubscription.css';
import '../styles/CustomPlan.css';

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
  const tenantId = useAuthStore((state) => state.tenantId);
  const subscriptionQuery = useSubscription(tenantId);
  const [now, setNow] = useState(Date.now);
  const [checkoutConflict, setCheckoutConflict] = useState(false);
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState('');
  const transition = useMutation({
    mutationFn: ({ action, body }) => action === 'accept' ? customOffersApi.acceptQuote(quoteId, body) : customOffersApi.rejectQuote(quoteId, body),
    onSuccess: async (result) => {
      setError('');
      setNotice(result?.state === 'expired'
        ? { variant: 'warning', message: t('billing.customPlan.offerExpired') }
        : { variant: 'success', message: result?.access_activated === false ? t('billing.customPlan.acceptedNotActivated') : t('billing.customPlan.transitionSaved') });
      await Promise.all([queryClient.invalidateQueries({ queryKey: ['custom-offer-quote', quoteId] }), queryClient.invalidateQueries({ queryKey: ['custom-offer-quotes'] })]);
    },
    onError: (cause) => setError(cause?.response?.data?.detail?.message || t('billing.customPlan.transitionFailed')),
  });
  const quote = quoteQuery.data;
  useEffect(() => {
    const cutoff = Date.parse(quote?.valid_until);
    if (!Number.isFinite(cutoff) || cutoff <= Date.now()) return undefined;
    const timer = setTimeout(() => setNow(Date.now()), Math.min(cutoff - Date.now() + 1, 2147483647));
    return () => clearTimeout(timer);
  }, [quote?.valid_until, now]);
  const wasPaid = quoteHasVerifiedActivation(quote);
  // A quote's acceptance window does not expire an already activated subscription.
  const expired = !wasPaid && quoteIsExpired(quote, Math.max(now, Date.now()));
  const existingAccess = hasActivePlanAccess(subscriptionQuery.data);
  const checkoutBlocked = checkoutConflict || subscriptionBlocksCustomCheckout(subscriptionQuery.data);
  const pending = quote?.state === 'submitted' && !expired;
  const isApproved = quote?.state === 'approved' && quote?.revision_state === 'approved';
  const isAccepted = quote?.state === 'accepted' && quote?.revision_state === 'accepted';
  const terms = quote?.commercial_terms || {};
  const checkoutSupported = (terms.currency === 'USD' && String(terms.billingPeriodMonths) === '1' && Number(terms.amount ?? terms.monthlyPriceUsd) > 0) || (terms.currency === 'JOD' && terms.paymentCurrency === 'USD' && Number(terms.paymentAmountUsd) > 0);
  const checkoutAvailable = Boolean(checkoutSupported && plansQuery.data?.paymentsEnabled && isAccepted && !expired && !checkoutBlocked && subscriptionQuery.isSuccess);
  const checkout = useMutation({
    mutationFn: async () => {
      // Another tab may have activated a subscription since this page loaded.
      const current = await subscriptionQuery.refetch();
      if (!current.isSuccess) throw new Error('subscription_check_failed');
      if (subscriptionBlocksCustomCheckout(current.data)) {
        setCheckoutConflict(true);
        throw new Error('subscription_exists');
      }
      if (quoteIsExpired(quote)) throw new Error('quote_expired');
      return customOffersApi.createCheckoutAttempt(quoteId, { idempotency_key: createIdempotencyKey() });
    },
    onSuccess: (result) => {
      if (result?.url && /^https:\/\//i.test(result.url)) window.location.assign(result.url);
      else setError(t('billing.customPlan.checkoutUnavailable'));
    },
    onError: (cause) => {
      const reason = cause?.response?.data?.detail?.reason || cause?.message;
      if (reason === 'subscription_exists') {
        setCheckoutConflict(true);
        void subscriptionQuery.refetch();
        setError(t('billing.customPlan.replacementUnavailable'));
      } else if (reason === 'quote_expired') {
        setNow(Date.now());
        void quoteQuery.refetch();
        setError(t('billing.customPlan.offerExpired'));
      } else setError(t('billing.customPlan.checkoutUnavailable'));
    },
  });

  const runTransition = (action) => {
    setError('');
    if (action === 'accept' && quoteIsExpired(quote)) { setNow(Date.now()); return; }
    transition.mutate({ action, body: { expected_revision: Number(quote.revision_number), idempotency_key: createIdempotencyKey() } });
  };
  const displayCode = (code) => quoteFeatureLabel(t, code);
  const quantities = quote?.feature_quantities || {};
  const included = quote?.configuration?.enabledFeatures || quote?.configuration?.enabled_features || [];

  if (quoteQuery.isPending) return <div className="billing-management-loading" aria-busy="true"><Skeleton height="80px" /><Skeleton height="300px" /></div>;
  if (quoteQuery.isError || !quote) return <EmptyState title={t('billing.customPlan.quoteUnavailableTitle')} description={quoteQuery.error?.response?.data?.detail?.message || t('billing.customPlan.quoteUnavailableBody')} action={<Button onClick={() => navigate(backToBuilder)}>{t('billing.customPlan.back')}</Button>} />;

  return <div className="billing-management-page custom-plan-page" dir={dir}>
    <Link className="billing-back-link" to={backToBuilder}><ArrowLeft className="ceopro-setup-direction-icon" size={15} />{t('billing.customPlan.backToBuilder')}</Link>
    <PageHeader title={t('billing.customPlan.quoteTitle')} subtitle={t('billing.customPlan.quoteReference', { id: quote.quote_id })} />
    {notice && <div className="billing-management-toast"><Toast variant={notice.variant} message={notice.message} onClose={() => setNotice(null)} /></div>}
    {error && <p className="billing-provider-note is-warning" role="alert">{error}</p>}
    <section className={`billing-payment-boundary custom-plan-offer-status${pending ? ' is-pending' : ''}`} role="status" aria-live="polite" aria-atomic="true">
      <span className={pending ? 'custom-plan-waiting' : undefined} aria-hidden="true"><LockKeyhole size={25} /></span>
      <h2>{t(pending ? 'billing.customPlan.pendingTitle' : 'billing.customPlan.status.' + (expired ? 'expired' : quote.state || 'submitted'))}</h2>
      {isApproved && !expired && <p>{t('billing.customPlan.offerReady')}</p>}
      {isAccepted && <p>{t(wasPaid ? 'billing.customPlan.paymentConfirmed' : 'billing.customPlan.acceptedNotActivated')}</p>}
      {pending && <><p>{t(existingAccess ? 'billing.customPlan.existingPendingBody' : 'billing.customPlan.pendingBody')}</p><p>{t('billing.customPlan.pendingNext')}</p></>}
      {quote.state === 'rejected' && <p>{t('billing.customPlan.offerRejected')}</p>}
      {expired && <p>{t('billing.customPlan.offerExpired')}</p>}
      {quote.valid_until && <small>{t('billing.customPlan.validUntil', { date: new Date(quote.valid_until).toLocaleDateString(locale) })}</small>}
    </section>
    {existingAccess && <p className="billing-provider-note" role="note">{t('billing.customPlan.currentAccessPreserved')} <Link to={routePaths.dashboard}>{t('billing.customPlan.returnDashboard')}</Link></p>}
    <Button variant="outline" disabled={quoteQuery.isFetching || subscriptionQuery.isFetching} onClick={() => { void quoteQuery.refetch(); void subscriptionQuery.refetch(); setNow(Date.now()); }}>{t('billing.customPlan.refreshStatus')}</Button>
    <section className="billing-management-section custom-plan-offer-terms">
      <header><h2>{t('billing.customPlan.offerTerms')}</h2></header>
      <ul>{included.map((code) => <li key={code}><Check size={15} />{displayCode(code)}</li>)}{Object.entries(quantities).map(([code, value]) => <li key={code}><Check size={15} />{displayCode(code)}: {new Intl.NumberFormat(locale).format(value)}</li>)}</ul>
      {(isApproved || isAccepted) && terms.currency && (terms.monthlyPriceUsd || terms.amount) && <div className="custom-plan-price"><span>{t('billing.customPlan.approvedPrice')}</span><strong>{new Intl.NumberFormat(locale, { style: 'currency', currency: terms.currency }).format(Number(terms.amount ?? terms.monthlyPriceUsd))}{terms.billingPeriodMonths ? ' / ' + t('billing.customPlan.period.' + (terms.periodCode || 'monthly')) : ''}</strong></div>}
      {(isApproved || isAccepted) && <p className="billing-provider-note" role="note">{t('billing.customPlan.priceIsApprovedOffer')}</p>}
      {(isApproved || isAccepted) && terms.paymentAmountUsd && <p>{t('billing.customPlan.usdPayment', { amount: terms.paymentAmountUsd })}</p>}
    </section>
    {(isApproved || isAccepted) && <div className="custom-plan-offer-actions">
      {isApproved && !expired && <Button variant="primary" loading={transition.isPending} loadingLabel={t('common.loading')} disabled={transition.isPending} onClick={() => runTransition('accept')}><Check size={15} />{t('billing.customPlan.acceptOffer')}</Button>}
      {isApproved && !expired && <Button variant="outline" loading={transition.isPending} loadingLabel={t('common.loading')} disabled={transition.isPending} onClick={() => runTransition('reject')}><X size={15} />{t('billing.customPlan.rejectOffer')}</Button>}
      {isAccepted && !wasPaid && checkoutAvailable && <Button variant="primary" loading={checkout.isPending} loadingLabel={t('common.loading')} disabled={checkout.isPending} onClick={() => checkout.mutate()}>{t('billing.customPlan.continueCheckout')}</Button>}
      {isAccepted && wasPaid && <Link className="billing-link-button" to={routePaths.billing}>{t('billing.customPlan.manageSubscription')}</Link>}
      {isAccepted && !wasPaid && !checkoutAvailable && <p className="billing-provider-note" role="note">{expired ? t('billing.customPlan.offerExpired') : checkoutBlocked ? t('billing.customPlan.replacementUnavailable') : !subscriptionQuery.isSuccess ? t('billing.customPlan.subscriptionCheckUnavailable') : !plansQuery.data?.paymentsEnabled ? t('billing.customPlan.checkoutPaymentsDisabled') : !checkoutSupported ? t('billing.customPlan.checkoutTermsUnsupported') : t('billing.customPlan.checkoutUnavailable')}</p>}
    </div>}
    {(expired || (quote.state !== 'approved' && quote.state !== 'accepted')) && <Button variant="outline" onClick={() => navigate(backToBuilder)}>{t('billing.customPlan.backToRequests')}</Button>}
    <p className="custom-plan-no-access" role="note">{t('billing.customPlan.noActivationNotice')}</p>
  </div>;
}
