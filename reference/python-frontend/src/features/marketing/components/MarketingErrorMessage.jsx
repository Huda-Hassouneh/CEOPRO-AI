import { Link } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { describeMarketingError } from '../lib/marketingErrors.js';

// One translated explanation for any failed marketing request; plan limits
// say when the allowance renews and link to Billing.
export function MarketingErrorMessage({ error, action, source, t, className = 'marketing-inline-error' }) {
  const { locale } = useI18n();
  const { key, values, billing, renewsOn } = describeMarketingError(error, { action, source });
  // Written out in the customer's language: a bare 2026-11-01 reads backwards in Arabic text.
  const renewal = renewsOn && new Intl.DateTimeFormat(locale, { dateStyle: 'long', timeZone: 'UTC' }).format(new Date(`${renewsOn}T00:00:00Z`));
  return (
    <p className={className} role="alert">
      {t(`marketingApex.errors.${key}`, values)}
      {renewal && <> {t('marketingApex.errors.renewsOn', { date: renewal })}</>}
      {billing && <> <Link to={routePaths.billing}>{t('marketingApex.errors.openBilling')}</Link></>}
    </p>
  );
}
