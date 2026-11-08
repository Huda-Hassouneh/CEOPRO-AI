import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../../auth/store/authStore.js';
import { validTrialOperation, trialJourneyPreviewEnabled } from '../api/trialJourneyApi.js';
import { trialConsentApi, trialConsentEnabled } from '../api/trialConsentApi.js';

export function TrialConsentPanel({ operationId, enabled = trialConsentEnabled && trialJourneyPreviewEnabled }) {
  const tenant = useAuthStore((state) => state.tenantId);
  const actor = useAuthStore((state) => state.user?.id);
  if (!enabled || !tenant || !actor || !validTrialOperation(operationId)) return null;
  return <ConsentPreparation key={`${tenant}:${actor}:${operationId}`} operation={operationId} tenant={tenant} actor={actor} />;
}

function ConsentPreparation({ operation, tenant, actor }) {
  const { t, locale, dir } = useI18n();
  const query = useQuery({ queryKey: ['trialConsent', tenant, actor, operation, locale],
    queryFn: ({ signal }) => trialConsentApi.prepare(operation, locale, signal),
    retry: false, gcTime: 0, staleTime: 0 });
  const data = !query.isError && !query.isFetching ? query.data : null;
  const terms = data?.commercial_terms;
  return <section className="billing-payment-boundary" dir={dir} aria-label={t('billing.trialConsent.title')}>
    <h2>{t('billing.trialConsent.title')}</h2>
    <p>{t('billing.trialConsent.businessRules')}</p>
    <p role="status">{query.isFetching ? t('common.loading') : t('billing.trialConsent.policyNotice')}</p>
    {terms && <dl>
      <dt>{t('billing.trialJourney.renewal')}</dt><dd><bdi>{terms.renewal_amount} {terms.currency}</bdi></dd>
      <dt>{t('billing.trialJourney.interval')}</dt><dd>{t('billing.trialJourney.months', { count: terms.interval_months })}</dd>
      <dt>{t('billing.trialJourney.duration')}</dt><dd>{t('billing.trialJourney.days', { count: terms.trial_duration_days })}</dd>
    </dl>}
    {data?.missing_approvals?.length > 0 && <ul aria-label={t('billing.trialConsent.missing')}>
      {data.missing_approvals.map((key) => <li key={key}>{t(`billing.trialConsent.missingFields.${key}`)}</li>)}
    </ul>}
    <ConsentActions key={locale}
      operation={operation} language={locale} preparation={data} />
    <p>{t('billing.trialConsent.providerNotice')}</p>
  </section>;
}

function ConsentActions({ operation, language, preparation }) {
  const { t } = useI18n();
  const [presentation, setPresentation] = useState(null);
  const [result, setResult] = useState(null);
  const present = useMutation({ mutationFn: () => trialConsentApi.present(operation, language),
    retry: false, onSuccess: (value) => { setPresentation(value); setResult(null); } });
  const approved = (!presentation || presentation.policy_revision === preparation?.policy_revision) && preparation?.state === 'prepared' && preparation?.missing_approvals?.length === 0
    && Boolean(preparation.agreement_text && preparation.policy_revision);
  return <div>
    {approved && <p style={{ whiteSpace: 'pre-wrap' }}>{preparation.agreement_text}</p>}
    <button type="button" disabled={!approved || present.isPending || Boolean(presentation)} onClick={() => present.mutate()}>{t('billing.trialConsent.present')}</button>
    <Acceptance key={`${presentation?.presentation_id || 'unchecked'}:${preparation?.policy_revision || 'unapproved'}`} operation={operation} language={language}
      presentation={presentation} enabled={approved} result={result} setResult={setResult} />
    {present.isError && <p role="alert">{t('billing.trialConsent.refused')}</p>}
  </div>;
}

function Acceptance({ operation, language, presentation, enabled, result, setResult }) {
  const { t } = useI18n();
  const [checked, setChecked] = useState(false);
  const accept = useMutation({ mutationFn: () => trialConsentApi.accept(operation, language, presentation, checked), retry: false, onSuccess: setResult });
  const withdraw = useMutation({ mutationFn: () => trialConsentApi.withdraw(operation, presentation), retry: false, onSuccess: setResult });
  const ready = enabled && presentation?.state === 'presented' && Boolean(presentation?.challenge) && !result;
  const pending = accept.isPending || withdraw.isPending;
  return <div>
    <label><input type="checkbox" checked={checked} disabled={!ready || pending} onChange={(event) => setChecked(event.target.checked)} />{t('billing.trialConsent.checkbox')}</label>
    <button type="button" disabled={!ready || !checked || pending} onClick={() => accept.mutate()}>{t('billing.trialConsent.accept')}</button>
    <button type="button" disabled={!presentation || pending || result?.state === 'withdrawn'} onClick={() => withdraw.mutate()}>{t('billing.trialConsent.withdraw')}</button>
    {result && <p role="status">{t(result.state === 'withdrawn' ? 'billing.trialConsent.withdrawn' : 'billing.trialConsent.recorded')}</p>}
    {(accept.isError || withdraw.isError) && <p role="alert">{t('billing.trialConsent.refused')}</p>}
    <p>{t('billing.trialConsent.cancellationNotice')}</p>
  </div>;
}
