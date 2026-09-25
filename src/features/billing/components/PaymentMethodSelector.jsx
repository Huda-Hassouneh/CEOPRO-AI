import { ArrowRight, LockKeyhole } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { PAYMENT_PROVIDER_ASSETS } from '../../data-connections/config/providerAssets.js';

export function PaymentMethodSelector({ onComplete, loading }) {
  const { t } = useI18n();

  return (
    <div className="ceopro-payment-method">
      <div className="ceopro-payment-panel">
        <div className="ceopro-provider-panel ceopro-stripe-panel">
          <img
            className="ceopro-provider-panel__logo ceopro-provider-panel__logo--stripe"
            src={PAYMENT_PROVIDER_ASSETS.stripe}
            alt="Stripe"
          />
          <p className="ceopro-payment-provider-copy">
            <LockKeyhole size={15} aria-hidden="true" />
            {t('billing.payment.secureHostedCheckout') ||
              'Card details and supported wallet options are collected securely on Stripe Checkout.'}
          </p>
          <Button
            className="ceopro-provider-button ceopro-provider-button--stripe"
            onClick={onComplete}
            loading={loading}
            loadingLabel={t('billing.payment.processing')}
            trailingIcon={<ArrowRight className="ceopro-setup-direction-icon" size={16} />}
          >
            {t('billing.payment.continueStripe') || 'Continue with Stripe'}
          </Button>
        </div>
      </div>

      <p className="ceopro-preview-notice" role="note">
        {t('billing.payment.providerNotice') ||
          'You will be redirected to the payment provider to complete checkout.'}
      </p>
    </div>
  );
}
