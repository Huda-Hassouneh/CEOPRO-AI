import { useMemo, useRef, useState } from 'react';
import { ArrowLeft, Check, SlidersHorizontal } from 'lucide-react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import Button from '../../../shared/components/ui/Button.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Select from '../../../shared/components/ui/Select.jsx';
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
  const [error, setError] = useState('');
  const [notice, setNotice] = useState(null);
  const [validating, setValidating] = useState(false);
  const idempotency = useRef(null);
  const catalog = catalogQuery.data;
  const modules = catalog?.modules || [];
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

  const toggleModule = (code) => {
    setEnabledFeatures((current) => current.includes(code) ? current.filter((item) => item !== code) : [...current, code]);
    setValidation(null); setPreview(null);
  };
  const toggleLimit = (code, checked) => {
    setSelectedLimits((current) => ({ ...current, [code]: checked }));
    setValidation(null); setPreview(null);
  };
  const formatFeature = (feature) => {
    const name = t('billing.customPlan.featureNames.' + feature.featureCode);
    const unit = feature.unit ? t('billing.customPlan.unitNames.' + feature.unit) : '';
    return { name: name === 'billing.customPlan.featureNames.' + feature.featureCode ? feature.featureCode.replaceAll('_', ' ') : name,
      unit: unit === 'billing.customPlan.unitNames.' + feature.unit ? feature.unit : unit };
  };

  const validate = async () => {
    setError(''); setNotice(null); setValidating(true); setValidation(null); setPreview(null);
    try {
      const result = await customOffersApi.validateConfiguration(configuration);
      setValidation(result);
      if (!result?.valid) return;
      // Preview is authoritative and read-only. Never derive or display a local price.
      const pricing = await customOffersApi.previewPricing(configuration);
      setPreview(pricing);
    } catch (cause) {
      setError(cause?.response?.data?.detail?.message || t('billing.customPlan.validationFailed'));
    } finally { setValidating(false); }
  };

  const requestQuote = () => {
    if (!validation?.valid || !configuration.enabled_features.length && !Object.keys(configuration.limits).length) return;
    const fingerprint = JSON.stringify(configuration);
    if (!idempotency.current || idempotency.current.fingerprint !== fingerprint) {
      idempotency.current = { fingerprint, key: createIdempotencyKey() };
    }
    submitQuote.mutate({ ...configuration, idempotency_key: idempotency.current.key });
  };

  if (catalogQuery.isPending) return <div className="billing-management-loading" aria-busy="true"><Skeleton height="80px" /><Skeleton height="420px" /></div>;
  if (catalogQuery.isError || !catalog) return <EmptyState title={t('billing.customPlan.loadErrorTitle')} description={catalogQuery.error?.response?.data?.detail?.message || t('billing.customPlan.loadErrorBody')} action={<Button onClick={() => catalogQuery.refetch()}>{t('billing.management.retry')}</Button>} />;

  return <div className="billing-management-page custom-plan-page" dir={dir}>
    <Link className="billing-back-link" to={returnTo}><ArrowLeft className="ceopro-setup-direction-icon" size={15} />{t('billing.customPlan.back')}</Link>
    <PageHeader title={t('billing.customPlan.title')} subtitle={t('billing.customPlan.subtitle')} />
    <p className="billing-provider-note" role="note">{t('billing.customPlan.manualReviewNotice')}</p>
    {error && <p className="billing-provider-note is-warning" role="alert">{error}</p>}
    {notice && <div className="billing-management-toast"><Toast variant={notice.variant} message={notice.message} onClose={() => setNotice(null)} /></div>}

    <div className="custom-plan-layout">
      <section className="billing-management-section custom-plan-options" aria-labelledby="custom-modules-title">
        <header><h2 id="custom-modules-title"><SlidersHorizontal size={18} />{t('billing.customPlan.modulesTitle')}</h2><p>{t('billing.customPlan.modulesDescription')}</p></header>
        <div className="custom-plan-module-grid">{modules.map((module) => {
          const code = module.featureCode;
          const checked = enabledFeatures.includes(code);
          return <label className={'custom-plan-option' + (checked ? ' is-selected' : '')} key={code}>
            <input type="checkbox" checked={checked} onChange={() => toggleModule(code)} />
            <span className="custom-plan-option__check">{checked && <Check size={15} />}</span>
            <span><strong>{t('billing.modules.' + code)}</strong><small>{t('billing.customPlan.moduleHelp.' + code)}</small></span>
          </label>;
        })}</div>

        <div className="custom-plan-allowances">
          <h2>{t('billing.customPlan.allowancesTitle')}</h2>
          <p>{t('billing.customPlan.allowancesDescription')}</p>
          {features.map((feature) => {
            const code = feature.featureCode;
            const label = formatFeature(feature);
            const checked = Boolean(selectedLimits[code]);
            return <div className="custom-plan-allowance" key={code}>
              <label><input type="checkbox" checked={checked} onChange={(event) => toggleLimit(code, event.target.checked)} /><span><strong>{t('billing.customPlan.featureNames.' + code) === 'billing.customPlan.featureNames.' + code ? label.name : t('billing.customPlan.featureNames.' + code)}</strong><small>{label.unit || feature.resetCycle || ''}</small></span></label>
              {checked && <Input type="number" min="0" step="1" inputMode="numeric" aria-label={t('billing.customPlan.quantityFor', { feature: label.name })} value={limitValues[code] ?? 0} onChange={(event) => { const value = event.target.value; if (/^\d*$/.test(value)) { setLimitValues((current) => ({ ...current, [code]: value === '' ? 0 : Number(value) })); setValidation(null); setPreview(null); } }} />}
            </div>;
          })}
        </div>

        {competitorEnabled && <div className="custom-plan-cadence">
          <Select label={t('billing.customPlan.monitoringCadence')} value={refreshFrequency} onChange={(event) => { setRefreshFrequency(event.target.value); setValidation(null); setPreview(null); }} options={[{ value: '', label: t('billing.customPlan.chooseCadence') }, ...(catalog.refreshFrequencies || []).map((value) => ({ value, label: t('billing.customPlan.cadences.' + value) }))]} />
          {trackedCompetitorsSelected && Number(limitValues.tracked_competitors) <= 0 && <small role="alert">{t('billing.customPlan.competitorLimitRequired')}</small>}
        </div>}
      </section>

      <aside className="custom-plan-summary" aria-live="polite">
        <h2>{t('billing.customPlan.summaryTitle')}</h2>
        <p>{t('billing.customPlan.summaryDescription')}</p>
        <ul>{configuration.enabled_features.map((code) => <li key={code}><Check size={15} />{t('billing.modules.' + code)}</li>)}{Object.entries(configuration.limits).map(([code, value]) => <li key={code}><Check size={15} />{t('billing.customPlan.featureNames.' + code)}: {new Intl.NumberFormat(locale).format(value)}</li>)}</ul>
        <Button fullWidth variant="outline" loading={validating} disabled={!configuration.enabled_features.length && !Object.keys(configuration.limits).length} onClick={validate}>{t('billing.customPlan.validate')}</Button>
        {validation?.valid && <p className="custom-plan-status" role="status">{t('billing.customPlan.configurationValid')}</p>}
        {preview?.pricingAvailable === true && (preview.monthlyPrice != null || preview.price != null) && <div className="custom-plan-price"><span>{t('billing.customPlan.serverPreview')}</span><strong>{new Intl.NumberFormat(locale, { style: 'currency', currency: preview.currency || catalog.initialCheckoutCurrency || 'USD' }).format(Number(preview.monthlyPrice ?? preview.price))}</strong></div>}
        {validation?.valid && preview?.pricingAvailable !== true && <p className="billing-provider-note custom-plan-price-unavailable" role="note">{t('billing.customPlan.priceUnavailable')}</p>}
        <Button fullWidth variant="primary" loading={submitQuote.isPending} disabled={!validation?.valid || submitQuote.isPending} onClick={requestQuote}>{t('billing.customPlan.requestQuote')}</Button>
        <small>{t('billing.customPlan.noActivationNotice')}</small>
      </aside>
    </div>

    <section className="billing-management-section" aria-labelledby="custom-quotes-title">
      <header><h2 id="custom-quotes-title">{t('billing.customPlan.myRequests')}</h2><p>{t('billing.customPlan.myRequestsDescription')}</p></header>
      {quotesQuery.isPending ? <Skeleton height="70px" /> : quotesQuery.isError ? <p className="billing-inline-error">{t('billing.customPlan.quotesUnavailable')}</p> : (quotesQuery.data?.quotes || []).length === 0 ? <p className="custom-plan-empty">{t('billing.customPlan.noRequests')}</p> : <ul className="custom-plan-quote-list">{quotesQuery.data.quotes.map((quote) => <li key={quote.quote_id}><span><strong>{t('billing.customPlan.quoteReference', { id: quote.quote_id })}</strong><small>{t('billing.customPlan.status.' + (quote.state || 'submitted'))} · {quote.created_at ? new Date(quote.created_at).toLocaleDateString(locale) : ''}</small></span><Button size="sm" variant="outline" onClick={() => navigate(routePaths.customPlanQuote.replace(':quoteId', encodeURIComponent(quote.quote_id)) + '?returnTo=' + encodeURIComponent(returnTo))}>{t('billing.customPlan.viewRequest')}</Button></li>)}</ul>}
    </section>
  </div>;
}