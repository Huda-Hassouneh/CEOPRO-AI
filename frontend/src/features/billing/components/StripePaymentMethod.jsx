import { ArrowRight, LockKeyhole } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';

export function StripePaymentMethod({ onContinue, loading = false, disabled = false }) {
  const { t } = useI18n();

  return (
    <section className="ceopro-payment-method" aria-labelledby="stripe-payment-title">
      <div className="ceopro-payment-panel">
        <div className="ceopro-provider-panel ceopro-stripe-panel">
          <h2 id="stripe-payment-title">Stripe</h2>
          <p className="ceopro-payment-provider-copy">
            <LockKeyhole size={15} aria-hidden="true" />
            {t('billing.onboarding.secureCheckout')}
          </p>
          <Button
            variant="primary"
            fullWidth
            onClick={onContinue}
            loading={loading}
            loadingLabel={t('billing.onboarding.processing')}
            disabled={disabled}
            trailingIcon={<ArrowRight size={16} aria-hidden="true" />}
          >
            {t('billing.onboarding.continueStripe')}
          </Button>
        </div>
      </div>
      <p className="ceopro-preview-notice" role="note">{t('billing.onboarding.stripeNotice')}</p>
    </section>
  );
}
