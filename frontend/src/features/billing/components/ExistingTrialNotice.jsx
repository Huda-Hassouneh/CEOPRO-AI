import { useI18n } from '../../../app/providers/I18nProvider.jsx';

export function ExistingTrialNotice({ endsAt }) {
  const { locale, t } = useI18n();
  const expiry = endsAt ? new Date(endsAt * 1000) : null;
  if (!expiry || Number.isNaN(expiry.getTime())) return null;
  const date = new Intl.DateTimeFormat(locale === 'ar' ? 'ar-JO' : 'en-US', {
    dateStyle: 'medium', timeStyle: 'medium', timeZone: 'UTC',
  }).format(expiry);
  return <section className="billing-existing-trial" aria-label={t('billing.payment.existingTrial')}>
    <strong>{t('billing.payment.existingTrial')}</strong>
    <p><time dateTime={expiry.toISOString()}>{t('billing.payment.existingTrialEndsAt', { date })}</time></p>
    <small>{t('billing.payment.preservedTrial')}</small>
  </section>;
}
