import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useAuthStore } from '../../auth/store/authStore.js';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import SegmentedControl from '../../../shared/components/ui/SegmentedControl.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import Toast from '../../../shared/components/ui/Toast.jsx';
import { BILLING_PERIODS } from '../config/billingPreviewData.js';
import { CurrentPlanCard } from '../components/CurrentPlanCard.jsx';
import { UsageLimitGrid } from '../components/UsageLimitGrid.jsx';
import { UpgradeRecommendation } from '../components/UpgradeRecommendation.jsx';
import { PlanCard } from '../components/PlanCard.jsx';
import { PlanComparisonTable } from '../components/PlanComparisonTable.jsx';
import { usePlans } from '../hooks/usePlans.js';
import { useSubscription } from '../hooks/useSubscription.js';
import { getUpgradeRecommendation } from '../utils/subscriptionRecommendations.js';
import '../styles/Billing.css';
import '../styles/PlansSubscription.css';

const planRank = { standard: 0, pro: 1, custom: 2 };

export function PlansSubscriptionPage() {
  const { t, locale, dir } = useI18n();
  const companyId = useAuthStore((state) => state.tenantId);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const plansQuery = usePlans();
  const subscriptionQuery = useSubscription(companyId);
  const [billingPeriod, setBillingPeriod] = useState('monthly');
  const [notice, setNotice] = useState(null);
  const compareRef = useRef(null);
  const dateFormatter = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }), [locale]);
  const numberFormatter = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);

  useEffect(() => {
    if (subscriptionQuery.data?.billingPeriod) setBillingPeriod(subscriptionQuery.data.billingPeriod);
  }, [subscriptionQuery.data?.billingPeriod]);

  if (plansQuery.isPending || subscriptionQuery.isPending) return <div className="billing-management-loading" aria-busy="true"><Skeleton height="78px" variant="rectangular" /><Skeleton height="190px" variant="rectangular" /><div>{[0, 1, 2].map((item) => <Skeleton key={item} height="150px" variant="rectangular" />)}</div></div>;
  if (plansQuery.isError || subscriptionQuery.isError) return <EmptyState title={t('billing.management.errorTitle')} description={t('billing.management.errorDescription')} action={<Button size="sm" onClick={() => { plansQuery.refetch(); subscriptionQuery.refetch(); }}>{t('billing.management.retry')}</Button>} />;

  const subscription = subscriptionQuery.data;
  const plans = plansQuery.data?.plans || [];
  const currentPlan = plans.find((plan) => plan.id === subscription?.planId);
  if (!subscription || !currentPlan) return <EmptyState title={t('billing.management.missingTitle')} description={t('billing.management.missingDescription')} />;

  const rawRecommendation = getUpgradeRecommendation(subscription, searchParams.get('reason'));
  const recommendation = rawRecommendation ? {
    titleKey: rawRecommendation.contextual ? `billing.management.context.${rawRecommendation.key}.title` : `billing.management.recommendation.${rawRecommendation.type}Title`,
    descriptionKey: rawRecommendation.contextual ? `billing.management.context.${rawRecommendation.key}.description` : `billing.management.recommendation.${rawRecommendation.type}Description`,
    values: rawRecommendation.key ? {
      metric: t(`billing.management.usageLabels.${rawRecommendation.key}`),
      used: numberFormatter.format(subscription.usage[rawRecommendation.key]),
      limit: numberFormatter.format(subscription.limits[rawRecommendation.key]),
    } : {},
  } : null;
  const periodOptions = BILLING_PERIODS.map((period) => ({
    value: period.value,
    label: period.months === 1 ? t('billing.periods.monthly') : t('billing.periods.monthCountLabel', { months: period.months }),
    badge: plans.every(p => p.discounts?.[period.value] === period.discountPercent) && period.discountPercent ? t('billing.periods.savePercent', { percent: period.discountPercent }) : undefined,
  }));

  const choosePlan = (plan) => {
    if (plan.id === 'custom') {
      setNotice({ variant: 'info', message: t('billing.management.contactUnavailable') });
      return;
    }
    navigate(`${routePaths.billingCheckout}?plan=${encodeURIComponent(plan.id)}&period=${encodeURIComponent(billingPeriod)}`);
  };

  return <div className="billing-management-page" dir={dir}>
    <PageHeader title={t('billing.management.title')} subtitle={t('billing.management.subtitle')} />
    <CurrentPlanCard subscription={subscription} plan={currentPlan} locale={locale} t={t} formatDate={(value) => dateFormatter.format(new Date(value))} />

    <section className="billing-management-section" aria-labelledby="usage-title"><header><h2 id="usage-title">{t('billing.management.usageTitle')}</h2><p>{t('billing.management.usageSubtitle')}</p></header><UsageLimitGrid usage={subscription.usage} limits={subscription.limits} locale={locale} t={t} /></section>
    <UpgradeRecommendation recommendation={recommendation} onCompare={() => compareRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })} t={t} />

    <section ref={compareRef} className="billing-management-section billing-compare-section" aria-labelledby="compare-title"><header className="billing-compare-header"><div><h2 id="compare-title">{t('billing.management.compareTitle')}</h2><p>{t('billing.management.compareSubtitle')}</p></div><SegmentedControl name="in-app-billing-period" value={billingPeriod} options={periodOptions} onChange={setBillingPeriod} ariaLabel={t('billing.periods.label')} /></header>
      <div className="ceopro-plan-grid billing-management-plans">{plans.map((plan) => {
        const current = plan.id === currentPlan.id;
        const trialConversion = current && subscription.status === 'trial' && plan.id === 'pro';
        const higherSelfService = plan.id !== 'custom' && planRank[plan.id] > planRank[currentPlan.id];
        const actionDisabled = current && !trialConversion || (!current && plan.id !== 'custom' && !higherSelfService);
        const actionLabel = current && !trialConversion
          ? t('billing.management.currentPlan')
          : plan.id === 'custom'
            ? t('billing.management.contactSales')
            : trialConversion
              ? t('billing.management.reviewSubscription')
              : higherSelfService
                ? t('billing.management.reviewUpgrade')
                : t('billing.management.notAvailable');
        return <PlanCard key={plan.id} plan={plan} currentPlan={current} billingPeriod={billingPeriod} onSelect={() => choosePlan(plan)} onBuild={() => choosePlan(plan)} actionLabel={actionLabel} actionDisabled={actionDisabled} />;
      })}</div>
    </section>

    <section className="billing-management-section" aria-labelledby="comparison-title"><header><h2 id="comparison-title">{t('billing.management.comparison.title')}</h2><p>{t('billing.management.comparison.subtitle')}</p></header><PlanComparisonTable plans={plans} currentPlanId={currentPlan.id} /></section>
    {notice && <div className="billing-management-toast"><Toast variant={notice.variant} message={notice.message} onClose={() => setNotice(null)} /></div>}
  </div>;
}
