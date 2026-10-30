import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, Check } from 'lucide-react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import Button from '../../../shared/components/ui/Button.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import { CustomPlanBuilder } from "../components/CustomPlanBuilder.jsx";
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';

import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import Toast from '../../../shared/components/ui/Toast.jsx';
import { customOffersApi, buildCustomOfferConfiguration, createIdempotencyKey } from '../api/customOffersApi.js';
import '../styles/Billing.css';
import '../styles/PlansSubscription.css';
import '../styles/CustomPlan.css';

const safeReturnPath = (value) => value === routePaths.onboardingPlan ? routePaths.onboardingPlan : routePaths.billing;

export function CustomPlanBuilderPage() {
  const { t, locale, dir } = useI18n();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const queryClient = useQueryClient();
  const returnTo = safeReturnPath(params.get('returnTo'));
  const catalogQuery = useQuery({ queryKey: ['custom-offers-configurator'], queryFn: customOffersApi.getConfigurator, staleTime: 5 * 60_000 });
  const quotesQuery = useQuery({ queryKey: ['custom-offer-quotes'], queryFn: () => customOffersApi.listQuotes(50), staleTime: 30_000 });
  const [enabledFeatures, setEnabledFeatures] = useState([]);
  const [selectedLimits, setSelectedLimits] = useState({});
  const [limitValues, setLimitValues] = useState({});
  const [refreshFrequency, setRefreshFrequency] = useState('');
  const [validation, setValidation] = useState(null);
  const [preview, setPreview] = useState(null);
  const [billingPeriod, setBillingPeriod] = useState('monthly');
  const revision = useRef(0);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState(null);
  const [validating, setValidating] = useState(false);
  const idempotency = useRef(null);
  const checkoutIntent = useRef(null);
  const catalog = catalogQuery.data;
  const features = catalog?.features || [];
  const trackedCompetitorsSelected = Boolean(selectedLimits.tracked_competitors);
  const competitorEnabled = enabledFeatures.includes('competitor_management');
  const configuration = useMemo(() => buildCustomOfferConfiguration({
    limits: Object.fromEntries(Object.keys(selectedLimits).filter((key) => selectedLimits[key]).map((key) => [key, limitValues[key] ?? 0])),
    enabledFeatures,
    refreshFrequency: competitorEnabled ? refreshFrequency || null : null,
  }), [competitorEnabled, enabledFeatures, limitValues, refreshFrequency, selectedLimits]);
  const submitQuote = useMutation({
    mutationFn: (body) => customOffersApi.requestQuote(body),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ['custom-offer-quotes'] });
      const quoteId = result?.quote_id;
      idempotency.current = null;
      if (quoteId) navigate(routePaths.customPlanQuote.replace(':quoteId', encodeURIComponent(quoteId)) + '?returnTo=' + encodeURIComponent(returnTo));
      else setNotice({ variant: 'success', message: t('billing.customPlan.requestSaved') });
    },
    onError: (cause) => setError(cause?.response?.data?.detail?.message || t('billing.customPlan.requestFailed')),
  });

  const formatFeature = (feature) => {
    const name = t('billing.customPlan.featureNames.' + feature.featureCode);
    const unit = feature.unit ? t('billing.customPlan.unitNames.' + feature.unit) : '';
    return { name: name === 'billing.customPlan.featureNames.' + feature.featureCode ? feature.featureCode.replaceAll('_', ' ') : name,
      unit: unit === 'billing.customPlan.unitNames.' + feature.unit ? feature.unit : unit };
  };

  const validate = useCallback(async () => {
    const current = ++revision.current;
    setError(''); setNotice(null); setValidating(true); setValidation(null); setPreview(null);
    try {
      const result = await customOffersApi.validateConfiguration(configuration);
      if (current !== revision.current) return;
      setValidation(result);
      if (!result?.valid) return;
      // Freeze server evidence; never derive a customer price locally.
      const pricing = await customOffersApi.previewPricing({ ...configuration, billing_period: billingPeriod, idempotency_key: createIdempotencyKey() });
      if (current === revision.current) setPreview(pricing);
    } catch (cause) {
      if (current === revision.current) setError(cause?.response?.data?.detail?.message || t('billing.customPlan.validationFailed'));
    } finally { if (current === revision.current) setValidating(false); }
  }, [configuration, billingPeriod, t]);

  useEffect(() => {
    revision.current += 1;
    if (!configuration.enabled_features.length && !Object.keys(configuration.limits).length) return;
    const timer = setTimeout(validate, 350);
    return () => { clearTimeout(timer); revision.current += 1; };
  }, [configuration, validate]);

  const checkout = useMutation({
    mutationFn: () => {
      if (checkoutIntent.current?.previewId !== preview.previewId) {
        checkoutIntent.current = { previewId: preview.previewId, key: createIdempotencyKey() };
      }
      return customOffersApi.automaticCheckout({ preview_id: preview.previewId, idempotency_key: checkoutIntent.current.key });
    },
    onSuccess: (result) => {
      if (result?.url && /^https:\/\//i.test(result.url)) window.location.assign(result.url);
      else setError(t('billing.customPlan.checkoutUnavailable'));
    },
    onError: (cause) => setError(cause?.response?.data?.detail?.message || t('billing.customPlan.checkoutUnavailable')),
  });

  const requestQuote = () => {
    if (!validation?.valid || !configuration.enabled_features.length && !Object.keys(configuration.limits).length) return;
    const fingerprint = JSON.stringify({ configuration, billingPeriod });
    if (!idempotency.current || idempotency.current.fingerprint !== fingerprint) {
      idempotency.current = { fingerprint, key: createIdempotencyKey() };
    }
    submitQuote.mutate({ ...configuration, billing_period: billingPeriod, ...(preview?.previewId ? { preview_id: preview.previewId } : {}), idempotency_key: idempotency.current.key });
  };

  if (catalogQuery.isPending) return <div className="billing-management-loading" aria-busy="true"><Skeleton height="80px" /><Skeleton height="420px" /></div>;
  if (catalogQuery.isError || !catalog) return <EmptyState title={t('billing.customPlan.loadErrorTitle')} description={catalogQuery.error?.response?.data?.detail?.message || t('billing.customPlan.loadErrorBody')} action={<Button onClick={() => catalogQuery.refetch()}>{t('billing.management.retry')}</Button>} />;

  return <div className="billing-management-page custom-plan-page" dir={dir}>
    <Link className="billing-back-link" to={returnTo}><ArrowLeft className="ceopro-setup-direction-icon" size={15} />{t('billing.customPlan.back')}</Link>
    <PageHeader title={t('billing.customPlan.title')} subtitle={t('billing.customPlan.subtitle')} />
    <p className="billing-provider-note" role="note">{t('billing.customPlan.automaticNotice')}</p>
    {error && <p className="billing-provider-note is-warning" role="alert">{error}</p>}
    {notice && <div className="billing-management-toast"><Toast variant={notice.variant} message={notice.message} onClose={() => setNotice(null)} /></div>}

    <div className="ceopro-custom-plan-layout">
      <section className="billing-management-section custom-plan-options" aria-labelledby="custom-modules-title">
        <CustomPlanBuilder features={[
          ...(catalog.modules || []).map((item) => ({ id:item.featureCode,code:item.featureCode,type:'boolean',name:t('billing.modules.'+item.featureCode),
            ...(item.featureCode === 'competitor_management' ? { configuration:{monitoringCadence:{defaultMinutes:1440,options:(catalog.refreshFrequencies||[]).map((value)=>({minutes:({hourly:60,daily:1440,weekly:10080,every_12_hours:720,every_6_hours:360})[value],code:value}))}} } : {}) })),
          ...features.map((item) => ({ id:item.featureCode,code:item.featureCode,type:'limit',name:formatFeature(item).name,unit:formatFeature(item).unit,min:item.min??0,step:item.step??1 })),
        ]} configuration={Object.fromEntries([
          ...(catalog.modules||[]).map((item)=>[item.featureCode,{selected:enabledFeatures.includes(item.featureCode),configuration:{monitoringFrequencyMinutes:({hourly:60,daily:1440,weekly:10080,every_12_hours:720,every_6_hours:360})[refreshFrequency]||1440}}]),
          ...features.map((item)=>[item.featureCode,{selected:Boolean(selectedLimits[item.featureCode]),limitValue:limitValues[item.featureCode]??item.min??0}]),
        ])} onChange={(code,value)=>{
          if ((catalog.modules||[]).some((item)=>item.featureCode===code)) {
            setEnabledFeatures((current)=>value.selected?[...new Set([...current,code])]:current.filter((item)=>item!==code));
            if(code==='competitor_management')setRefreshFrequency(({60:'hourly',1440:'daily',10080:'weekly',720:'every_12_hours',360:'every_6_hours'})[value.configuration?.monitoringFrequencyMinutes]||'daily');
          } else {
            setSelectedLimits((current)=>({...current,[code]:value.selected}));
            setLimitValues((current)=>({...current,[code]:value.limitValue}));
          }
          setValidation(null);setPreview(null);setValidating(false);
        }} />
        {trackedCompetitorsSelected && Number(limitValues.tracked_competitors)<=0 && <p role="alert">{t('billing.customPlan.competitorLimitRequired')}</p>}
      </section>

      <aside className="ceopro-plan-summary" aria-live="polite">
        <h2>{t('billing.customPlan.summaryTitle')}</h2>
        <p>{t('billing.customPlan.summaryDescription')}</p>
        <label>{t('billing.customPlan.periodLabel')}<select value={billingPeriod} onChange={(event) => { setBillingPeriod(event.target.value); setPreview(null); setValidation(null); }}>
          {['monthly', 'three-months', 'six-months'].map((period) => <option key={period} value={period}>{t('billing.customPlan.period.' + period)}</option>)}
        </select></label>
        <ul>{configuration.enabled_features.map((code) => <li key={code}><Check size={15} />{t('billing.modules.' + code)}</li>)}{Object.entries(configuration.limits).map(([code, value]) => <li key={code}><Check size={15} />{t('billing.customPlan.featureNames.' + code)}: {new Intl.NumberFormat(locale).format(value)}</li>)}</ul>
        <Button fullWidth variant="outline" loading={validating} disabled={!configuration.enabled_features.length && !Object.keys(configuration.limits).length} onClick={validate}>{t('billing.customPlan.validate')}</Button>
        {validation?.valid && <p className="custom-plan-status" role="status">{t('billing.customPlan.configurationValid')}</p>}
        {preview?.pricingAvailable === true && (preview.monthlyPrice != null || preview.price != null) && <div className="custom-plan-price"><span>{t('billing.customPlan.serverPreview')}</span><strong>{new Intl.NumberFormat(locale, { style: 'currency', currency: preview.currency || catalog.initialCheckoutCurrency || 'USD' }).format(Number(preview.price ?? preview.monthlyPrice))}</strong></div>}
        {preview?.months > 1 && <p>{t('billing.custom.monthlyBaseBeforeDiscount', { price: new Intl.NumberFormat(locale, { style: 'currency', currency: 'JOD' }).format(Number(preview.monthlyPrice)), percent: preview.discountPercent })}</p>}
        {validation?.valid && preview?.pricingAvailable !== true && <p className="billing-provider-note custom-plan-price-unavailable" role="note">{t('billing.customPlan.priceUnavailable')}</p>}
        {preview?.paymentAmount && <p>{t('billing.customPlan.usdPayment', { amount: preview.paymentAmount })}</p>}
        {preview?.reviewRequired && <div role="status"><strong>{t('billing.customPlan.reviewRequired')}</strong><ul>{(preview.reasons || []).map((reason) => <li key={reason}>{t('billing.customPlan.reviewReasons.' + reason.split(':')[0])}{reason.includes(':') ? ': ' + formatFeature({ featureCode: reason.split(':')[1] }).name : ''}</li>)}</ul></div>}
        {preview?.checkoutBlocker && <p role="alert">{t('billing.customPlan.existingSubscription')}</p>}
        {preview && !preview.paymentsEnabled && <p>{t('billing.customPlan.checkoutPaymentsDisabled')}</p>}
        {preview && !preview.reviewRequired ? <Button fullWidth variant="primary" loading={checkout.isPending} disabled={!preview.checkoutAllowed || validating || checkout.isPending} onClick={() => checkout.mutate()}>{t('billing.customPlan.continueCheckout')}</Button> : <Button fullWidth variant="primary" loading={submitQuote.isPending} disabled={!validation?.valid || validating || submitQuote.isPending} onClick={requestQuote}>{t('billing.customPlan.requestQuote')}</Button>}
        <small>{t('billing.customPlan.noActivationNotice')}</small>
      </aside>
    </div>

    <section className="billing-management-section" aria-labelledby="custom-quotes-title">
      <header><h2 id="custom-quotes-title">{t('billing.customPlan.myRequests')}</h2><p>{t('billing.customPlan.myRequestsDescription')}</p></header>
      {quotesQuery.isPending ? <Skeleton height="70px" /> : quotesQuery.isError ? <p className="billing-inline-error">{t('billing.customPlan.quotesUnavailable')}</p> : (quotesQuery.data?.quotes || []).length === 0 ? <p className="custom-plan-empty">{t('billing.customPlan.noRequests')}</p> : <ul className="custom-plan-quote-list">{quotesQuery.data.quotes.map((quote) => <li key={quote.quote_id}><span><strong>{t('billing.customPlan.quoteReference', { id: quote.quote_id })}</strong><small>{t('billing.customPlan.status.' + (quote.state || 'submitted'))} · {quote.created_at ? new Date(quote.created_at).toLocaleDateString(locale) : ''}</small></span><Button size="sm" variant="outline" onClick={() => navigate(routePaths.customPlanQuote.replace(':quoteId', encodeURIComponent(quote.quote_id)) + '?returnTo=' + encodeURIComponent(returnTo))}>{t('billing.customPlan.viewRequest')}</Button></li>)}</ul>}
    </section>
  </div>;
}
