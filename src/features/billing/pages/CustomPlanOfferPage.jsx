import { ArrowLeft, ArrowRight, LockKeyhole } from 'lucide-react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMemo, useState } from 'react';
import useSWR from 'swr';

import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import Button from '../../../shared/components/ui/Button.jsx';
import Card from '../../../shared/components/ui/Card.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Select from '../../../shared/components/ui/Select.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import Table from '../../../shared/components/ui/Table.jsx';
import Toast from '../../../shared/components/ui/Toast.jsx';
import { billingApi, getApiError } from '../api/billingApi.js';
import '../styles/Billing.css';
import '../styles/PlansSubscription.css';

const swrOptions = { shouldRetryOnError: false, revalidateOnFocus: false };
const tr = (t, key, fallback, params) => {
  const value = t(key, params);
  return value === key ? fallback : value;
};

export function CustomPlanOfferPage() {
  const { quoteId } = useParams();
  const { t, locale, dir } = useI18n();
  const navigate = useNavigate();
  const [period, setPeriod] = useState('monthly');
  const [accepting, setAccepting] = useState(false);
  const [notice, setNotice] = useState(null);

  const { data: response, error, isLoading } = useSWR(
    quoteId ? ['custom-plan-offer', quoteId] : null,
    () => billingApi.getCustomPlanOffer(quoteId),
    swrOptions,
  );
  const offer = response?.data;
  const options = Array.isArray(offer?.billingOptions) && offer.billingOptions.length
    ? offer.billingOptions
    : [{ period: 'monthly', months: 1, discountPercent: 0 }];
  const selected = options.find((option) => option.period === period) ?? options[0];

  const formatCurrency = useMemo(
    () => (amount, currency = 'JOD') => new Intl.NumberFormat(locale, { style: 'currency', currency }).format(Number(amount || 0)),
    [locale],
  );

  if (isLoading) {
    return <div className="billing-checkout-loading"><Skeleton height="82px" variant="rectangular" /><Skeleton height="360px" variant="rectangular" /></div>;
  }

  if (error || !offer) {
    return <EmptyState title={tr(t, 'billing.customOffer.errorTitle', 'Custom offer unavailable')} description={getApiError(error).message || tr(t, 'billing.customOffer.errorDescription', 'This offer is unavailable, expired, or no longer accessible.')} action={<Button onClick={() => navigate(routePaths.billing)}>{tr(t, 'billing.customOffer.back', 'Back to billing')}</Button>} />;
  }

  const total = Number(offer.finalPrice || 0) * Number(selected.months || 1) * (1 - Number(selected.discountPercent || 0) / 100);
  const name = locale === 'ar' && offer.name_ar ? offer.name_ar : offer.name;
  const description = locale === 'ar' && offer.description_ar ? offer.description_ar : offer.description;
  const accepted = offer.status === 'accepted';

  const accept = async () => {
    setAccepting(true);
    setNotice(null);
    try {
      const acceptedResponse = await billingApi.acceptCustomPlanQuote(offer.id);
      const plan = acceptedResponse?.data;
      if (!plan?.id) throw new Error('Accepted quote did not return a plan.');
      navigate(`${routePaths.billingCheckout}?plan=${encodeURIComponent(plan.id)}&period=${encodeURIComponent(selected.period)}`);
    } catch (requestError) {
      setNotice({ variant: 'error', message: getApiError(requestError).message });
    } finally {
      setAccepting(false);
    }
  };

  return (
    <div className="billing-checkout-page billing-custom-offer-page" dir={dir}>
      <Link className="billing-back-link" to={routePaths.billing}>
        <ArrowLeft className="ceopro-setup-direction-icon" size={15} />
        {tr(t, 'billing.customOffer.back', 'Back to billing')}
      </Link>

      <div className="billing-custom-offer-hero">
        <span className="billing-custom-offer-eyebrow">{tr(t, 'billing.customOffer.eyebrow', 'Private custom plan')}</span>
        <h1>{name}</h1>
        {description && <p>{description}</p>}
      </div>

      <div className="billing-checkout-layout">
        <div className="billing-custom-offer-main">
          <Card>
            <h2>{tr(t, 'billing.customOffer.included', 'What is included')}</h2>
            <Table
              ariaLabel={tr(t, 'billing.customOffer.included', 'What is included')}
              data={offer.features ?? []}
              columns={[
                { header: tr(t, 'billing.catalog.fields.feature', 'Feature'), render: (item) => locale === 'ar' && item.feature?.name_ar ? item.feature.name_ar : item.feature?.name ?? item.featureId },
                { header: tr(t, 'billing.catalog.fields.limit', 'Limit'), render: (item) => item.feature?.type === 'boolean' ? tr(t, 'billing.customOffer.includedValue', 'Included') : item.limitValue ?? tr(t, 'billing.customOffer.unlimited', 'Custom / unlimited') },
              ]}
            />
          </Card>
        </div>

        <aside className="billing-payment-boundary billing-custom-offer-summary">
          <span><LockKeyhole size={24} /></span>
          <h2>{tr(t, 'billing.customOffer.summary', 'Your tailored offer')}</h2>
          <p>{tr(t, 'billing.customOffer.privateNotice', 'Internal vendor costs and CEOPRO pricing formulas are never exposed in the customer offer.')}</p>
          <Select
            label={tr(t, 'billing.checkoutInApp.billingPeriod', 'Billing period')}
            value={selected.period}
            onChange={(event) => setPeriod(event.target.value)}
            options={options.map((option) => ({ value: option.period, label: option.months === 1 ? tr(t, 'billing.periods.monthly', 'Monthly') : `${option.months} months${option.discountPercent ? ` · ${option.discountPercent}% off` : ''}` }))}
          />
          <div className="billing-custom-offer-price">
            <span>{tr(t, 'billing.customOffer.price', 'Subscription price')}</span>
            <strong>{formatCurrency(total, offer.currency)}</strong>
          </div>
          {offer.trialPeriodValue > 0 && <small>{offer.trialPeriodValue} {tr(t, 'billing.customOffer.trialDays', 'trial days included')}</small>}
          <Button fullWidth trailingIcon={<ArrowRight className="ceopro-setup-direction-icon" size={15} />} loading={accepting} onClick={accept}>
            {accepted ? tr(t, 'billing.customOffer.continueCheckout', 'Continue to checkout') : tr(t, 'billing.customOffer.accept', 'Accept plan & continue')}
          </Button>
        </aside>
      </div>

      {notice && <div className="billing-management-toast"><Toast variant={notice.variant} message={notice.message} onClose={() => setNotice(null)} /></div>}
    </div>
  );
}
