import { useQuery } from '@tanstack/react-query';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { billingApi, getApiError } from '../api/customerBillingApi.js';
export function PlanChangePreview({ planId, billingPeriod, subscription }) {
  const { t, locale } = useI18n();
  const preview = useQuery({ queryKey: ['plan-change-preview', planId, billingPeriod],
    queryFn: () => billingApi.previewChange({ planId, billingPeriod }), enabled: Boolean(subscription?.hasStripeSubscription), retry: false });
  if (!subscription?.hasStripeSubscription) return <p>{t('billing.changePreview.checkoutTrial')}</p>;
  if (preview.isPending) return <p role="status">{t('billing.changePreview.loading')}</p>;
  if (preview.isError) return <p className="billing-inline-error" role="alert">{getApiError(preview.error).message}</p>;
  const data = preview.data;
  const display = (value) => typeof value === 'boolean' ? t('billing.changePreview.' + (value ? 'enabled' : 'disabled')) : value === null ? t('common.unlimited') : value === 'not_included' ? t('billing.changePreview.disabled') : String(value ?? '—');
  return <section aria-label={t('billing.changePreview.title')}>
    <p>{t('billing.changePreview.' + data.timing)}</p>
    {data.effective_at && <p>{t('billing.changePreview.effectiveAt')}: {new Date(data.effective_at).toLocaleString(locale)}</p>}
    <p>{t('billing.changePreview.' + data.payment_policy)}</p>
    <p>{t('billing.changePreview.verifiedRights')}</p>
    <ul>{data.feature_changes.map((item) => <li key={item.feature_code}>
      {t('billing.customPlan.featureNames.' + item.feature_code)}: {display(item.before)} → {display(item.after)}
      {item.over_limit && <strong> — {t('billing.changePreview.overLimit')}</strong>}
    </li>)}</ul>
    <p>{t('billing.changePreview.dataPreserved')}</p>
    <p>{t('billing.changePreview.credits')}</p>
  </section>;
}
