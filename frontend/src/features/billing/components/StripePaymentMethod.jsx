import { LockKeyhole } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';

export function StripePaymentMethod() {
  const { t } = useI18n();

  return (
    <div className="ceopro-payment-security" role="note">
      <p><LockKeyhole size={15} aria-hidden="true" />{t('billing.payment.poweredByStripe')}</p>
      <small>{t('billing.onboarding.stripeNotice')}</small>
    </div>
  );
}
